"""Task4: offline READ/facade and pure contribution acceptance boundaries.

Semantic verifier outputs and fixed membership are frozen test inputs. Delivery,
preprocessing, SHA reads, projection, and HTTP GET are the actual implementations.
No fixture invokes a queue, collector, model, or historical successful canary.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from infrastructure.owned_io import SafeRoot
from v4.manager_workbench import announcement_delivery as deliveries
from v4.manager_workbench import announcement_membership as membership
from v4.manager_workbench import announcement_update as owner
from v4.manager_workbench import api
from v4.manager_workbench.contracts import HK, JobState

DAY = "20261021"
OLD, CURRENT, NEIGHBOR = "a" * 32, "b" * 32, "c" * 32
REAL_SEMANTIC_SNAPSHOT = owner.AnnouncementUpdate.semantic_recovery_snapshot


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(autouse=True)
def disconnected(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Task4 must not access a socket/provider")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "isolated-state"
    root.mkdir()
    io = SafeRoot(root)
    cursors, jobs, semantics = {}, {}, {}
    store = SimpleNamespace(root=root, io=io, cursor=cursors.get)
    svc = SimpleNamespace(store=store, jobs=SimpleNamespace(get=jobs.__getitem__),
                          config=SimpleNamespace(capture_root=tmp_path / "isolated-capture"))
    svc.config.capture_root.mkdir()
    base = {"state": "PARTIAL", "source_date": "CANNOT_CONFIRM", "target_trade_date": "CANNOT_CONFIRM",
            "stocks": [], "failures": [], "pending": [], "gaps": [], "counts": {}}
    monkeypatch.setattr(owner, "read_pinned_candidates", lambda: deepcopy(base))
    gate = {"status": "VERIFIED", "basis": "USER_FIXED_UNIVERSE", "target_date": DAY,
            "codes": ["HK.00001", "HK.00002"], "authority_sha256": "f" * 64}
    monkeypatch.setattr(membership, "resolve_membership_gate", lambda *_args: deepcopy(gate))
    monkeypatch.setattr(owner.AnnouncementUpdate, "semantic_recovery_snapshot",
                        lambda _self, job_id, _report_sha: deepcopy(semantics[job_id]))
    update = owner.AnnouncementUpdate(svc, clock=lambda: datetime(2026, 10, 21, 18, tzinfo=HK))

    def add(job_id, *, article_id=None, symbol="HK.00001", reason=None, indexed_result=True):
        aid = article_id or "ARTICLE:" + job_id[0]
        reason = reason or "accepted " + aid
        article = {"article_id": aid, "symbol": symbol, "name": "Fixture", "reason": reason,
                   "source_sha256": sha((aid + "source").encode()), "body_sha256": sha((aid + "body").encode()),
                   "queue_key": sha((job_id + aid).encode()), "result_sha256": sha((aid + "result").encode()),
                   "state": "SUCCEEDED", "source_coverage": "COMPLETE_ARTICLE",
                   "disposition": "SELECTED_EVENT", "direction": "POSITIVE", "source_origins": [],
                   "review_status": "MODEL_CANDIDATE_UNREVIEWED"}
        stock = {"symbol": symbol, "name": "Fixture", "articles": [article], "reasons": [reason],
                 "review_status": "MODEL_CANDIDATE_UNREVIEWED"}
        capture = {"artifact_ref": "capture/" + job_id + ".json", "sha256": sha(job_id.encode())}
        report = {"job_id": job_id, "target_date": DAY, "accounting_closed": True,
                  "capture_product": capture, "counts": {}, "catalogue": [article]}
        report_raw = encoded(report)
        io.write_bytes(f"announcement_flash/jobs/{job_id}/preprocessing-report.json", report_raw)
        delivered = {"schema": deliveries.SCHEMA, "job_id": job_id, "target_trade_date": DAY,
                     "preprocessing_report_sha256": sha(report_raw), "capture_product": capture,
                     "stocks": [stock], "articles": [article], "state": "PARTIAL", "counts": {"SUCCEEDED": 1}}
        binding = deliveries.publish(io, job_id, delivered)
        cursors.setdefault("announcement_flash_delivery_index", {"items": []})["items"].append(
            {"job_id": job_id, "target_date": DAY})
        if indexed_result:
            result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": job_id,
                      "target_trade_date": DAY, "state": "PARTIAL", "counts": {}, "stocks": [stock],
                      "failures": [], "pending": []}
            result_raw = encoded(result)
            io.write_bytes(f"announcement_flash/jobs/{job_id}/result.json", result_raw)
            cursors.setdefault("announcement_flash_result_index", {"items": []})["items"].append(
                {"job_id": job_id, "target_date": DAY, "result_sha256": sha(result_raw)})
        semantics[job_id] = {"status": "BLOCKED", "eligible": False, "job_id": job_id, "target_date": DAY,
                             "report_sha256": sha(report_raw), "delivery_sha256": binding["sha256"],
                             "checkpoint_state": "SUCCEEDED", "semantic_review_state": "SUCCEEDED",
                             "semantic_review_sha256": "d" * 64, "extension_sha256": "e" * 64,
                             "quarantined_results": []}
        jobs[job_id] = SimpleNamespace(job_id=job_id, state=JobState.PARTIAL,
                                      context=SimpleNamespace(target_date=DAY), step="DONE", completed_count=1,
                                      total_count=1, failure_code=None, last_progress_at="2026-10-21T18:00:00+08:00")
        return delivered, binding, report

    def latest(job_id=CURRENT, date=DAY):
        cursors["announcement_flash_latest"] = {"job_id": job_id, "target_date": date, "state": "QUEUED"}

    return SimpleNamespace(root=root, io=io, cursors=cursors, jobs=jobs, semantics=semantics,
                           svc=svc, update=update, add=add, latest=latest)


def test_new_latest_never_revives_rejected_old_article_and_keeps_good_same_stock(case):
    old, _, _ = case.add(OLD, reason="rejected old reason")
    case.add(CURRENT, reason="legitimate current reason")
    case.add(NEIGHBOR, symbol="HK.00002")
    case.semantics[OLD]["quarantined_results"] = [
        {key: old["articles"][0][key] for key in ("queue_key", "result_sha256")}]
    case.latest()

    value = case.update.read(DAY)

    assert [row["symbol"] for row in value["stocks"]] == ["HK.00001", "HK.00002"]
    assert value["stocks"][0]["reasons"] == ["legitimate current reason"]
    assert [a["article_id"] for s in value["stocks"] for a in s["articles"]] == ["ARTICLE:b", "ARTICLE:c"]
    assert {c["job_id"] for c in value["day_summary"]["contributions"]} == {OLD, CURRENT, NEIGHBOR}


def test_valid_same_day_old_contribution_survives_new_latest(case):
    case.add(OLD, symbol="HK.00002")
    case.add(CURRENT)
    case.latest()
    value = case.update.read(DAY)
    assert [s["symbol"] for s in value["stocks"]] == ["HK.00002", "HK.00001"]
    assert value["day_summary"]["candidate_stocks"] == 2


def test_bad_historical_pin_does_not_mask_independent_current_get(case, monkeypatch):
    case.add(CURRENT)
    case.latest()
    def unavailable():
        raise owner.CandidateEvidenceError("PINNED_EVIDENCE_SHA_MISMATCH")
    monkeypatch.setattr(owner, "read_pinned_candidates", unavailable)
    app = FastAPI()
    app.include_router(api.create_router(case.svc))
    before = {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    def no_write(*_args, **_kwargs):
        pytest.fail("GET attempted a state write")
    monkeypatch.setattr(SafeRoot, "write_bytes", no_write)
    with TestClient(app) as client:
        response = client.get(api.PREFIX + "/announcement-flash", params={"target_date": DAY})
    assert response.status_code == 200, response.text
    value = response.json()["data"]
    assert value["state"] != "UNAVAILABLE"
    assert value["current_job"]["job_id"] == CURRENT
    assert value["day_summary"]["availability"] == "AVAILABLE"
    assert value["counts"]["displayed_stocks"] == 1
    assert value["historical_candidates"]["availability"] == "UNAVAILABLE"
    assert {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()} == before


def test_requested_day_mismatch_has_no_current_job_or_foreign_delivery(case):
    case.add(CURRENT)
    case.latest()
    value = case.update.read("20261022")
    assert value["job"] is None
    assert value["current_job"] is None
    assert value["day_summary"]["contributions"] == []
    assert value["stocks"] == []


def test_last_delivery_is_explicitly_distinct_from_actual_failed_current_attempt(case):
    case.add(CURRENT)
    case.add(OLD, symbol="HK.00002")
    case.latest()
    case.jobs[CURRENT].state = JobState.FAILED
    case.jobs[CURRENT].step = "FAILED"
    case.jobs[CURRENT].failure_code = "FIXTURE_STOP"
    case.io.write_bytes(f"announcement_flash/jobs/{CURRENT}/progress.json", encoded(
        {"step": "FAILED", "failure_code": "FIXTURE_STOP", "completed": 1, "total": 2}))
    value = case.update.read(DAY)
    assert value["daily_delivery"]["job_id"] == OLD
    assert value["current_job"]["job_id"] == CURRENT
    assert value["current_job"]["state"] == "FAILED"
    assert value["current_job"]["progress"]["step"] == "FAILED"
    assert value["day_summary"]["availability"] == "AVAILABLE"


@pytest.mark.parametrize("field", ["job_id", "target_date", "report_sha256", "delivery_sha256"])
def test_receipt_identity_conflict_isolated_without_blocking_valid_neighbor(case, field):
    case.add(OLD)
    case.add(CURRENT, symbol="HK.00002")
    case.latest()
    case.semantics[OLD][field] = "0" * (32 if field == "job_id" else 64)
    value = case.update.read(DAY)
    assert [s["symbol"] for s in value["stocks"]] == ["HK.00002"]
    assert value["isolated_contributions"][0]["job_id"] == OLD
    assert value["day_summary"]["candidate_stocks"] == 1


@pytest.mark.parametrize("damage", ["source", "delivery_sha", "report_sha", "delivery_date"])
def test_source_or_stored_binding_conflict_isolated_and_good_neighbor_survives(case, damage):
    delivered, binding, _ = case.add(OLD)
    case.add(CURRENT, symbol="HK.00002")
    case.latest()
    if damage in {"source", "delivery_date"}:
        delivered = deepcopy(delivered)
        if damage == "source":
            delivered["stocks"][0]["articles"][0]["source_sha256"] = "0" * 64
        else:
            delivered["target_trade_date"] = "20261022"
        binding = deliveries.publish(case.io, OLD, delivered)
        case.semantics[OLD]["delivery_sha256"] = binding["sha256"]
    else:
        ref = binding["artifact_ref"] if damage == "delivery_sha" else f"announcement_flash/jobs/{OLD}/preprocessing-report.json"
        case.io.write_bytes(ref, case.io.read_bytes(ref) + b" ")
    value = case.update.read(DAY)
    assert [s["symbol"] for s in value["stocks"]] == ["HK.00002"]
    assert value["isolated_contributions"][0]["job_id"] == OLD


def test_missing_receipt_is_diagnostic_and_not_a_legal_day_candidate(case):
    case.add(OLD)
    case.add(CURRENT, symbol="HK.00002")
    case.latest()
    case.semantics[OLD] = {"status": "BLOCKED", "eligible": False, "job_id": OLD,
                           "reason": "SEMANTIC_REVIEW_UNAVAILABLE", "quarantined_results": []}
    value = case.update.read(DAY)
    assert [s["symbol"] for s in value["stocks"]] == ["HK.00002"]
    diagnostic = value["unreviewed_contributions"][0]
    assert diagnostic["job_id"] == OLD
    assert diagnostic["stocks"][0]["review_status"] == "MODEL_CANDIDATE_UNREVIEWED"
    assert value["day_summary"]["candidate_stocks"] == 1


def test_pure_projection_does_not_mutate_inputs_and_filters_before_same_code_merge(case):
    from v4.manager_workbench.announcement_projection import project_delivery_contribution
    delivered, _, _ = case.add(OLD)
    review = case.semantics[OLD]
    review["quarantined_results"] = [{key: delivered["articles"][0][key]
                                      for key in ("queue_key", "result_sha256")}]
    before = deepcopy((delivered, review))
    projected = project_delivery_contribution(delivered, review)
    assert projected["stocks"] == []
    assert projected["availability"] == "AVAILABLE"
    assert (delivered, review) == before


def test_actual_semantic_verifier_missing_evidence_never_authenticates_delivery(case, monkeypatch):
    case.add(CURRENT)
    case.latest()
    monkeypatch.setattr(owner.AnnouncementUpdate, "semantic_recovery_snapshot", REAL_SEMANTIC_SNAPSHOT)
    value = case.update.read(DAY)
    assert value["stocks"] == []
    assert value["day_summary"]["contribution_count"] == 0
    assert value["unreviewed_contributions"][0]["stocks"][0]["articles"][0]["article_id"] == "ARTICLE:b"
    assert value["semantic_recovery"]["status"] == "BLOCKED"
    assert not value["semantic_recovery"].get("semantic_review_sha256")


def test_failed_current_without_delivery_keeps_independent_old_day_summary(case):
    case.add(OLD, symbol="HK.00002")
    case.latest()
    case.jobs[CURRENT] = SimpleNamespace(job_id=CURRENT, state=JobState.FAILED,
        context=SimpleNamespace(target_date=DAY), step="FAILED", completed_count=0, total_count=1,
        failure_code="FIXTURE_PRE_DISPATCH_FAILURE", last_progress_at=None)
    value = case.update.read(DAY)
    assert value["current_job"]["state"] == "FAILED"
    assert value["daily_delivery"]["job_id"] == OLD
    assert value["daily_delivery_is_current_job"] is False
    assert value["day_summary"]["contribution_count"] == 1
    assert value["day_summary"]["contributions"][0]["job_id"] == OLD


def test_cursor_alone_does_not_invent_queued_current_attempt(case):
    case.add(OLD)
    case.latest()
    value = case.update.read(DAY)
    assert value["current_job"] is None
    assert value["job"] is None
    assert value["day_summary"]["candidate_stocks"] == 1


def test_catalogue_issuer_cannot_be_reassigned_to_another_eligible_stock(case):
    old, binding, report = case.add(OLD)
    case.add(CURRENT, symbol="HK.00002")
    case.latest()
    old_raw = case.io.read_bytes(binding["artifact_ref"])
    receipt_sha = case.semantics[OLD]["semantic_review_sha256"]
    altered = deepcopy(old)
    altered["stocks"][0]["symbol"] = "HK.00002"
    altered["stocks"][0]["articles"][0]["symbol"] = "HK.00002"
    altered["articles"][0]["symbol"] = "HK.00002"
    changed = deliveries.publish(case.io, OLD, altered)
    case.semantics[OLD]["delivery_sha256"] = changed["sha256"]

    value = case.update.read(DAY)

    assert report["catalogue"][0]["symbol"] == "HK.00001"
    assert case.semantics[OLD]["semantic_review_sha256"] == receipt_sha
    assert [c["job_id"] for c in value["day_summary"]["contributions"]] == [CURRENT]
    assert value["stocks"][0]["reasons"] == ["accepted ARTICLE:b"]
    assert value["isolated_contributions"][0]["job_id"] == OLD
    assert value["isolated_contributions"][0]["reason"] == "DELIVERY_PREPROCESSING_ISSUER_CHANGED"
    assert case.io.read_bytes(binding["artifact_ref"]) == old_raw


@pytest.mark.parametrize("damage", [
    "stock_null", "stock_articles_null", "stock_articles_mapping", "stock_article_null",
    "delivery_articles_null", "delivery_article_null",
])
def test_malformed_historical_delivery_isolated_before_nested_access(case, monkeypatch, damage):
    old, _, _ = case.add(OLD)
    case.add(CURRENT, symbol="HK.00002")
    case.latest()
    altered = deepcopy(old)
    if damage == "stock_null":
        altered["stocks"] = [None]
    elif damage == "stock_articles_null":
        altered["stocks"][0]["articles"] = None
    elif damage == "stock_articles_mapping":
        altered["stocks"][0]["articles"] = {"article_id": "malformed-container"}
    elif damage == "stock_article_null":
        altered["stocks"][0]["articles"] = [None]
    elif damage == "delivery_articles_null":
        altered["articles"] = None
    else:
        altered["articles"] = [None]
    binding = deliveries.publish(case.io, OLD, altered)
    case.semantics[OLD]["delivery_sha256"] = binding["sha256"]
    before = {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    def no_write(*_args, **_kwargs):
        pytest.fail("READ attempted a state write")
    monkeypatch.setattr(SafeRoot, "write_bytes", no_write)

    value = case.update.read(DAY)

    assert [c["job_id"] for c in value["day_summary"]["contributions"]] == [CURRENT]
    assert [s["symbol"] for s in value["stocks"]] == ["HK.00002"]
    assert value["isolated_contributions"][0]["job_id"] == OLD
    assert value["isolated_contributions"][0]["availability"] == "ISOLATED"
    assert value["isolated_contributions"][0]["reason"].startswith("DELIVERY_")
    assert {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()} == before


def test_result_reference_conflict_names_artifact_without_rejecting_independent_delivery(case):
    _, binding, _ = case.add(CURRENT)
    case.latest()
    case.cursors["announcement_flash_result_index"]["items"][0]["result_sha256"] = "0" * 64

    value = case.update.read(DAY)

    assert value["day_summary"]["candidate_stocks"] == 1
    isolated = value["isolated_contributions"][0]
    assert isolated["job_id"] == CURRENT
    assert isolated["artifact_kind"] == "RESULT_REFERENCE"
    assert isolated["artifact_ref"] == f"announcement_flash/jobs/{CURRENT}/result.json"
    assert isolated["expected_sha256"] == "0" * 64
    accepted = value["day_summary"]["contributions"][0]
    assert accepted["job_id"] == CURRENT
    assert accepted["artifact_kind"] == "DAILY_DELIVERY"
    assert accepted["artifact_ref"] == binding["artifact_ref"]
    assert accepted["expected_sha256"] == binding["sha256"]
