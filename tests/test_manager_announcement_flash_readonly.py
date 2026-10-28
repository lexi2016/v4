from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench import api
from v4.manager_workbench import announcement_update as update_module
from v4.manager_workbench.announcement_candidate import read_pinned_candidates
from v4.manager_workbench.announcement_update import AnnouncementUpdate
from v4.manager_workbench.contracts import HK, JobState


class FakeStore:
    def __init__(self):
        self.values = {}
        self.root = "/tmp/mwb-announcement-test"
        self.files = {}
        self.io = SimpleNamespace(read_bytes=self._read, write_bytes=self._write, files=self._list)

    def _read(self, ref, **_kwargs):
        try:
            return self.files[ref]
        except KeyError as exc:
            raise FileNotFoundError(ref) from exc

    def _write(self, ref, data, **_kwargs):
        self.files[ref] = data

    def _list(self, prefix):
        marker = prefix.rstrip("/") + "/"
        return [name[len(marker):] for name in self.files
                if name.startswith(marker) and "/" not in name[len(marker):]]

    def lock(self, _key):
        return nullcontext()

    def cursor(self, key):
        return self.values.get(key)

    def set_cursor(self, key, value):
        self.values[key] = value


class FakeJobs:
    def __init__(self):
        self.jobs = {}
        self.submissions = []

    def submit(self, context, worker):
        job = SimpleNamespace(job_id=f"{len(self.jobs) + 1:032x}", state=JobState.QUEUED,
                              step="QUEUED", context=context, completed_count=0, total_count=None,
                              failure_code=None, last_progress_at=None)
        self.jobs[job.job_id] = job
        self.submissions.append((context, worker))
        return job

    def get(self, job_id):
        return self.jobs[job_id]


def service():
    return SimpleNamespace(
        config=SimpleNamespace(capture_root="/private/capture", capture_lease_root="/private/leases"),
        store=FakeStore(), jobs=FakeJobs(),
    )


def test_announcement_get_defaults_to_latest_and_accepts_explicit_history_date(monkeypatch):
    targets = []

    class ReadOnlyUpdate:
        def __init__(self, _service):
            pass

        def read(self, target_date=None):
            targets.append(target_date)
            return {"state": "READY", "requested_target_date": target_date, "gaps": []}

    monkeypatch.setattr(api, "AnnouncementUpdate", ReadOnlyUpdate)
    app = FastAPI()
    svc = service()
    app.include_router(api.create_router(svc))
    client = TestClient(app)

    latest = client.get(api.PREFIX + "/announcement-flash")
    history = client.get(api.PREFIX + "/announcement-flash?target_date=20261015")

    assert latest.status_code == history.status_code == 200
    assert latest.json()["data"]["requested_target_date"] is None
    assert history.json()["data"]["requested_target_date"] == "20261015"
    assert targets == [None, "20261015"]
    assert svc.jobs.submissions == []


def test_merge_stocks_unions_duplicate_article_origins_and_keeps_distinct_articles():
    def origin(ref, product_sha, row_sha):
        return {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_ref": ref,
                "source_product_sha256": product_sha, "row_fingerprint_sha256": row_sha}

    first_origin = origin("capture-a.json#1", "a" * 64, "1" * 64)
    second_origin = origin("capture-b.json#1", "b" * 64, "2" * 64)
    third_origin = origin("capture-c.json#1", "c" * 64, "3" * 64)
    distinct_origin = origin("capture-d.json#1", "d" * 64, "4" * 64)
    base = [{"symbol": "HK.00001", "name": "Company", "reasons": ["original"],
             "review_status": "MODEL_CANDIDATE_UNREVIEWED", "reuse_status": None,
             "articles": [
                 {"article_id": "NOTICE:1", "title": "Original title", "reason": "original",
                  "source_origins": [first_origin]},
                 {"article_id": "NOTICE:2", "title": "Distinct notice", "reason": "distinct",
                  "source_origins": []},
             ]}]
    extra = [{"symbol": "HK.00001", "name": "Company", "reasons": [],
              "review_status": "MODEL_CANDIDATE_UNREVIEWED", "reuse_status": None,
              "articles": [
                  {"article_id": "NOTICE:1", "title": "Duplicate copy", "source_origins": [first_origin, second_origin]},
                  {"article_id": "NOTICE:1", "title": "Another duplicate", "source_origins": [third_origin]},
                  {"article_id": "NOTICE:3", "title": "New distinct notice", "reason": "new",
                   "source_origins": [distinct_origin]},
              ]}]

    merged = update_module._merge_stocks(base, extra)

    assert [article["article_id"] for article in merged[0]["articles"]] == [
        "NOTICE:1", "NOTICE:2", "NOTICE:3"]
    assert merged[0]["articles"][0]["title"] == "Original title"
    assert merged[0]["articles"][0]["source_origins"] == [first_origin, second_origin, third_origin]
    assert merged[0]["articles"][2]["source_origins"] == [distinct_origin]
    assert base[0]["articles"][0]["source_origins"] == [first_origin]


def test_merge_stocks_deduplicates_new_stock_articles_and_unions_origins_without_mutating_input():
    first_origin = {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_ref": "capture-a.json#1",
                    "source_product_sha256": "a" * 64, "row_fingerprint_sha256": "1" * 64}
    second_origin = {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_ref": "capture-b.json#1",
                     "source_product_sha256": "b" * 64, "row_fingerprint_sha256": "2" * 64}
    same_article = {"article_id": "NOTICE:1", "title": "Notice", "reason": "Reason",
                    "source_origins": [first_origin]}
    second_copy = {**same_article, "source_origins": [second_origin]}
    distinct_article = {"article_id": "NOTICE:2", "title": "Distinct", "reason": "Distinct reason",
                        "source_origins": []}
    incoming = [{"symbol": "HK.00001", "name": "Company", "reasons": ["Reason", "Distinct reason"],
                 "review_status": "MODEL_CANDIDATE_UNREVIEWED",
                 "articles": [same_article, second_copy, distinct_article]}]

    merged = update_module._merge_stocks([], incoming)

    assert [article["article_id"] for article in merged[0]["articles"]] == ["NOTICE:1", "NOTICE:2"]
    assert merged[0]["articles"][0]["source_origins"] == [first_origin, second_origin]
    assert merged[0]["reasons"] == ["Reason", "Distinct reason"]
    assert incoming[0]["articles"] == [same_article, second_copy, distinct_article]


def test_pinned_projection_has_verified_candidate_and_failure_population():
    result = read_pinned_candidates()
    assert len(result["stocks"]) == 20
    assert result["counts"] == {
        "source_catalogue_articles": 392,
        "model_succeeded": 367,
        "selected_model_articles": 21,
        "model_candidate_stocks": 19,
        "reused_reviewed_stocks": 1,
        "failed": 18,
        "pending": 5,
        "body_gaps": 1,
        "displayed_stocks": 20,
    }
    assert result["target_trade_date"] == "CANNOT_CONFIRM"
    assert all(stock["reasons"] and stock["articles"] for stock in result["stocks"])
    assert sum(len(stock["articles"]) for stock in result["stocks"]) == 22


def test_announcement_get_is_pure_and_returns_pinned_evidence(monkeypatch):
    svc = service()
    def forbidden_grant(*_args, **_kwargs):
        raise AssertionError("GET must not acquire a capture lease")
    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore.grant", forbidden_grant)

    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).get(api.PREFIX + "/announcement-flash?target_date=20261016")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["counts"]["displayed_stocks"] == 0
    assert payload["data"]["counts"]["failed"] == 0
    assert payload["data"]["counts"]["pending"] == 0
    assert payload["data"]["membership"]["status"] == "CANNOT_CONFIRM"
    assert payload["data"]["counts"]["membership_unknown_stocks"] == 20
    assert payload["data"]["job"] is None
    assert svc.jobs.submissions == []
    assert "/private/" not in str(payload["data"])


def test_announcement_get_projects_pinned_candidates_through_target_date_membership(monkeypatch):
    svc = service()
    pinned = read_pinned_candidates()
    excluded = {"HK.09963", "HK.08637", "HK.01319", "HK.01799", "HK.02290"}
    members = sorted(stock["symbol"] for stock in pinned["stocks"] if stock["symbol"] not in excluded)
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": "2026-10-16T13:02:00+08:00", "market": "HK_CONNECT",
            "owner": "v35_dispatcher.research_panel_daily_hk", "authority_sha256": "e" * 64,
            "authority_version": "version", "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59.501065+08:00", "member_count": 698,
            "codes": members}
    monkeypatch.setattr("v4.manager_workbench.announcement_membership.resolve_membership_gate",
                        lambda *_args: dict(gate))

    value = AnnouncementUpdate(svc).read("20261016")

    assert len(value["stocks"]) == 15
    assert len(value["membership_excluded_stocks"]) == 5
    assert value["membership_unknown_stocks"] == []
    assert value["counts"]["displayed_stocks"] == 15
    assert value["target_trade_date"] == "CANNOT_CONFIRM"
    assert value["membership"]["target_date"] == "20261016"


def test_unavailable_pinned_candidate_keeps_counts_unknown(monkeypatch):
    svc = service()
    def unavailable():
        raise update_module.CandidateEvidenceError("PINNED_EVIDENCE_SHA_MISMATCH")
    monkeypatch.setattr(update_module, "read_pinned_candidates", unavailable)

    value = AnnouncementUpdate(svc).read("20261016")

    assert value["state"] == "UNAVAILABLE"
    assert value["target_trade_date"] == "CANNOT_CONFIRM"
    assert value["counts"]["displayed_stocks"] is None
    assert value["gaps"][0]["code"] == "PINNED_EVIDENCE_SHA_MISMATCH"


def test_safe_runner_failure_code_is_visible_in_announcement_status():
    svc = service()
    job_id = "c" * 32
    failure_code = "FLASH_PIPELINE_RUNTIMEERROR"
    svc.jobs.jobs[job_id] = SimpleNamespace(
        job_id=job_id, state=JobState.FAILED,
        context=SimpleNamespace(target_date="20261016"), step="FAILED",
        completed_count=0, total_count=None, failure_code=failure_code,
        last_progress_at="2026-10-16T11:23:53+08:00",
    )
    svc.store.values["announcement_flash_latest"] = {"job_id": job_id, "target_date": "20261016"}
    svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"] = update_module._canonical({
        "step": "FAILED", "failure_code": failure_code,
        "diagnostic": {"exception_type": "RuntimeError", "stack_frames": []},
    })

    value = AnnouncementUpdate(svc).read("20261016")

    assert value["job"]["failure_code"] == failure_code


def _saved_partial_result_for(job_id, failure_code, target_date="20261016"):
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": target_date,
            "cutoff": "2026-10-16T14:57:00+08:00", "market": "HK_CONNECT",
            "owner": "v35_dispatcher.research_panel_daily_hk", "authority_sha256": "e" * 64,
            "authority_version": "v1", "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59+08:00", "member_count": 100,
            "codes": [f"HK.{number:05d}" for number in range(10000, 10100)]}

    def stock(number, prefix):
        symbol = f"HK.{number:05d}"
        article = {"article_id": f"EASTMONEY:{prefix}{number:05d}", "title": f"公告{number}",
                   "publication_date": "2026-10-16", "symbol": symbol, "name": f"公司{number}",
                   "disposition": "SELECTED_EVENT", "direction": "POSITIVE", "reason": "人工复核前候选。",
                   "impact": [], "body_sha256": str(number % 10) * 64, "source_sha256": str((number + 1) % 10) * 64,
                   "source_origins": [], "review_status": "MODEL_CANDIDATE_UNREVIEWED", "reuse_status": None}
        return {"symbol": symbol, "name": article["name"], "reasons": [article["reason"]],
                "articles": [article], "review_status": article["review_status"], "reuse_status": None}

    result_stocks = [stock(number, "CURRENT") for number in range(10015, 10026)]
    current_ids = [f"EASTMONEY:AN20261016{number:04d}" for number in range(137)]
    failures = [{"article_id": current_ids[number], "symbol": "HK.10000", "title": f"失败{number}",
                 "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY", "stage": "validator"}
                for number in range(8)]
    failures.extend({"article_id": f"EASTMONEY:PRIOR_FAIL_{number}", "symbol": "HK.10000",
                     "title": f"保留历史失败{number}", "failure_code": "ANNOUNCEMENT_EVIDENCE_INCOMPLETE"}
                    for number in range(9))
    failures.extend({"article_id": "EASTMONEY:LONG", "symbol": "HK.10098", "title": "长文",
                     "part_index": number + 1, "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY"}
                    for number in range(17))
    pending = [{"article_id": "EASTMONEY:LONG", "symbol": "HK.10098", "title": "长文",
                "part_index": 1, "part_count": 22, "queue_status": "FAILED",
                "queue_reason": "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM",
                "repair_status": "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED"}]
    pending.extend({"article_id": "EASTMONEY:LONG", "symbol": "HK.10098", "title": "长文",
                    "part_index": number + 2, "part_count": 22,
                    "queue_reason": "LONG_BODY_PART_REPAIR_GATED"}
                   for number in range(16))
    pending.extend({"article_id": f"EASTMONEY:LONG_SYNTH_{number}", "symbol": "HK.10098",
                    "title": "长文综合", "queue_reason": "SAVED_SYNTHESIS_IDENTITY_CONFLICT"}
                   for number in range(2))
    return gate, {
        "schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": job_id,
        "state": "PARTIAL", "target_trade_date": target_date,
        "updated_at": "2026-10-16T21:20:00+08:00",
        "counts": {"capture_rows": 354, "selected_model_articles": 11, "new_candidate_stocks": 11,
                   "failed": 25, "queue_pending": 16, "body_gaps": 0,
                   "queue": {"incremental_succeeded_matched": 129,
                             "incremental_failed_matched": 8, "incremental_pending_matched": 0,
                             "long_body_parts_failed": 17, "long_body_parts_succeeded": 17,
                             "long_body_parts_pending": 16,
                             "long_body_parts_cannot_confirm": 1,
                             "long_body_synthesis_pending": 2}},
        "stocks": result_stocks, "failures": failures, "pending": pending, "gaps": [],
        "system_stop": {"failure_code": failure_code, "stage": "FLASH_SELECTION",
                        "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                        "failed_at": "2026-10-16T21:17:16+08:00"},
        "membership_gate": gate,
        "provenance": {"current_capture_bindings": {article_id: {"membership_status": "IN"}
                                                     for article_id in current_ids},
                       "queue_version_associations": [{"article_id": article_id} for article_id in current_ids]},
        "current_batch": {"article_count": 137,
                          "article_status_counts": {"succeeded": 129, "failed": 8, "pending": 0},
                          "selected_articles": 11, "candidate_stocks": 11},
        "materialization": {"mode": "SAVED_VALIDATED_QUEUE_ONLY", "failure_code": failure_code,
                            "failed_at": "2026-10-16T21:17:16+08:00", "queue_dispatches": 0,
                            "model_calls": 0, "status": "PARTIAL_PUBLISHED_WITH_ORIGINAL_FAILURE"},
    }


def test_failed_saved_materialization_is_indexed_and_overlays_prior_pending_in_api(monkeypatch):
    svc = service()
    job_id = "9" * 32
    failure_code = "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
    finished_at = "2026-10-16T21:17:16+08:00"
    job = SimpleNamespace(job_id=job_id, state=JobState.FAILED, step="FLASH_SELECTION",
                          context=SimpleNamespace(target_date="20261016"), failure_code=failure_code,
                          failed_steps=["FLASH_SELECTION"], finished_at=finished_at,
                          last_progress_at=finished_at, completed_count=138, total_count=171)
    svc.jobs.jobs[job_id] = job
    svc.config.shared_root = "/private/shared"
    input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                   "job_id": job_id, "target_date": "20261016"}
    progress_value = {"step": "FAILED", "failure_code": failure_code, "failed_step": "FLASH_SELECTION",
                      "updated_at": finished_at}
    svc.store.files[f"announcement_flash/jobs/{job_id}/input.json"] = update_module._canonical(input_value)
    progress_raw = update_module._canonical(progress_value) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"] = progress_raw
    svc.store.values["announcement_flash_latest"] = {"job_id": job_id, "target_date": "20261016",
                                                       "state": "FAILED"}
    gate, result = _saved_partial_result_for(job_id, failure_code)
    command_calls = []

    class FinishedProcess:
        returncode = 0
        def poll(self):
            return self.returncode

    def fake_popen(command, **_kwargs):
        command_calls.append(command)
        assert "--materialize-saved-partial" in command
        assert command[command.index("--failure-code") + 1] == failure_code
        raw = update_module._canonical(result) + b"\n"
        svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"] = raw
        return FinishedProcess()

    update = AnnouncementUpdate(svc, popen=fake_popen)
    materialized = update.materialize_failed_partial(job_id)
    assert materialized["materialization"]["model_calls"] == 0
    assert len(command_calls) == 1
    assert svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"] == progress_raw
    assert svc.jobs.get(job_id).state == JobState.FAILED
    assert svc.jobs.get(job_id).failure_code == failure_code
    assert svc.jobs.get(job_id).finished_at == finished_at
    assert svc.store.values["announcement_flash_result_index"]["items"] == [{
        "job_id": job_id, "target_date": "20261016",
        "result_sha256": update_module._sha(svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"])}]
    assert update.materialize_failed_partial(job_id)["job_id"] == job_id
    assert len(command_calls) == 1

    old_stocks = []
    for number in range(10000, 10015):
        symbol = f"HK.{number:05d}"
        old_stocks.append({"symbol": symbol, "name": f"旧公司{number}", "reasons": ["旧候选"],
                           "articles": [{"article_id": f"EASTMONEY:OLD{number:05d}", "symbol": symbol,
                                         "reason": "旧候选。"}]})
    old_pending = [{"article_id": article_id, "symbol": "HK.10000", "title": "旧占位",
                    "queue_reason": "PRIOR_QUEUE_PENDING_NOT_RETRIED"}
                   for article_id in result["provenance"]["current_capture_bindings"]]
    pinned = {"state": "PARTIAL", "source_date": "20261015", "target_trade_date": "CANNOT_CONFIRM",
              "updated_at": "2026-10-15T18:35:00+08:00", "stocks": old_stocks,
              "failures": [], "pending": old_pending, "gaps": [], "system_stop": None,
              "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                         "buy_gate_updated": False, "orders_sent": False},
              "counts": {"source_catalogue_articles": 392, "model_succeeded": 367,
                         "selected_model_articles": 21, "model_candidate_stocks": 14,
                         "reused_reviewed_stocks": 0, "failed": 18, "pending": 137,
                         "body_gaps": 1, "displayed_stocks": 15}}
    monkeypatch.setattr(update_module, "read_pinned_candidates", lambda: pinned)
    monkeypatch.setattr("v4.manager_workbench.announcement_membership.resolve_membership_gate",
                        lambda *_args: dict(gate))
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).get(api.PREFIX + "/announcement-flash?target_date=20261016")
    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert view["state"] == "PARTIAL"
    assert view["target_trade_date"] == "20261016"
    assert view["updated_at"] == result["updated_at"]
    assert view["counts"]["displayed_stocks"] == 26
    assert view["counts"]["current_batch_candidate_stocks"] == 11
    assert view["counts"]["model_succeeded"] == 129
    assert view["counts"]["model_failed_articles"] == 8
    assert view["counts"]["failure_rows"] == 34
    assert view["counts"]["model_pending_articles"] == 0
    assert view["counts"]["long_body_part_failed"] == 17
    assert view["counts"]["long_body_part_pending"] == 16
    assert view["counts"]["long_body_part_cannot_confirm"] == 1
    assert view["counts"]["long_body_synthesis_pending"] == 2
    assert view["counts"]["pending"] == 0
    assert len(view["pending"]) == 19
    assert view["pending"][0]["queue_reason"] == "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM"
    assert view["job"]["state"] == "FAILED"
    assert view["job"]["failure_code"] == failure_code
    assert view["job"]["finished_at"] == finished_at
    assert view["incremental"]["state"] == "PARTIAL"
    assert view["incremental"]["system_stop"]["failed_at"] == finished_at


def test_later_runner_failure_automatically_materializes_saved_partial(monkeypatch):
    svc = service()
    svc.config.shared_root = "/private/shared"
    job_id = "8" * 32
    failure_code = "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
    finished_at = "2026-10-16T21:17:16+08:00"
    capture_raw = b"verified capture product"
    capture_sha = update_module._sha(capture_raw)
    saved_ref = {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha}
    calls = []

    class FakeCaptureStore:
        def __init__(self, *_args, **_kwargs):
            self.io = SimpleNamespace(read_bytes=lambda *_args, **_kwargs: capture_raw)
        def grant(self, **_kwargs): pass
        def revoke(self): pass

    class FinishedProcess:
        def __init__(self, returncode): self.returncode = returncode
        def poll(self): return self.returncode

    gate, result = _saved_partial_result_for(job_id, failure_code)
    def fake_popen(command, **_kwargs):
        calls.append(command)
        if "--materialize-saved-partial" in command:
            svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"] = update_module._canonical(result) + b"\n"
            return FinishedProcess(0)
        svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"] = update_module._canonical({
            "step": "FAILED", "failure_code": failure_code, "failed_step": "FLASH_SELECTION",
            "updated_at": finished_at}) + b"\n"
        return FinishedProcess(1)

    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore", FakeCaptureStore)
    monkeypatch.setattr("v4.manager_workbench.inputs.capture.capture_window",
                        lambda *_args, **_kwargs: {"saved_ref": saved_ref})
    monkeypatch.setattr("v4.manager_workbench.announcement_membership.resolve_membership_gate",
                        lambda *_args: dict(gate))
    svc.jobs = SimpleNamespace(update=lambda *_args, **_kwargs: None)
    job = SimpleNamespace(job_id=job_id,
                          context=SimpleNamespace(target_date="20261016",
                                                  model_copy=lambda **_kwargs: SimpleNamespace(
                                                      target_date="20261016", cutoff="2026-10-16T10:30:00+08:00",
                                                      scope_refs={})),
                          completed_count=0, total_count=None, execution_refs=[], step="FLASH_SELECTION")
    try:
        AnnouncementUpdate(svc, popen=fake_popen, sleep=lambda _seconds: None)._work(job)
    except update_module.StepFailure as exc:
        assert str(exc) == failure_code
    else:
        raise AssertionError("the original run failure must remain the terminal job outcome")
    assert len(calls) == 2
    assert "--materialize-saved-partial" not in calls[0]
    assert "--materialize-saved-partial" in calls[1]
    assert svc.store.values["announcement_flash_result_index"]["items"][0]["job_id"] == job_id
    assert json.loads(svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"])["failure_code"] == failure_code


def test_flash_runner_launch_disables_bytecode_cache(monkeypatch):
    svc = service()
    svc.config.shared_root = "/private/shared"
    job_id = "d" * 32
    capture_raw = b"verified capture product"
    capture_sha = update_module._sha(capture_raw)
    saved_ref = {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha}
    command_calls = []

    class FakeCaptureStore:
        def __init__(self, *_args, **_kwargs):
            self.io = SimpleNamespace(read_bytes=lambda *_args, **_kwargs: capture_raw)

        def grant(self, **_kwargs):
            pass

        def revoke(self):
            pass

    class FinishedProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    def fake_popen(command, **kwargs):
        command_calls.append((command, kwargs))
        return FinishedProcess()

    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore", FakeCaptureStore)
    monkeypatch.setattr("v4.manager_workbench.inputs.capture.capture_window",
                        lambda *_args, **_kwargs: {"saved_ref": saved_ref})
    svc.jobs = SimpleNamespace(update=lambda *_args, **_kwargs: None)
    job = SimpleNamespace(
        job_id=job_id,
        context=SimpleNamespace(model_copy=lambda **_kwargs: SimpleNamespace(
            target_date="20261016", cutoff="2026-10-16T10:30:00+08:00")),
        completed_count=0,
        total_count=None,
        execution_refs=[],
    )

    try:
        AnnouncementUpdate(svc, popen=fake_popen)._work(job)
    except update_module.StepFailure as exc:
        assert str(exc) == "FLASH_RESULT_INVALID"
    else:
        raise AssertionError("missing runner result should stop after launch")

    assert len(command_calls) == 1
    command, kwargs = command_calls[0]
    assert command[0] == str(update_module.RUNNER_PYTHON)
    assert command[1] == "-B"
    assert command[2] == str(update_module.RUNNER_SCRIPT)
    assert command[-2:] == ["--shared-root", "/private/shared"]
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    stored_input = json.loads(svc.store.files[f"announcement_flash/jobs/{job_id}/input.json"])
    assert stored_input["cutoff"] == "2026-10-16T10:30:00+08:00"
    assert stored_input["membership_gate"]["status"] == "CANNOT_CONFIRM"


def test_manual_update_post_is_idempotent_for_the_same_minute(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 30, tzinfo=HK)
    update = AnnouncementUpdate(svc, clock=lambda: now)
    first = update.start("20261016")
    second = update.start("20261016")

    assert first.job_id == second.job_id
    assert len(svc.jobs.submissions) == 1
    context, worker = svc.jobs.submissions[0]
    assert context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert context.scope_refs["requested_lanes"] == []
    assert callable(worker)


def _saved_raw_citation_parent_fixture():
    svc = service()
    parent_id, root_id, ancestor_id = "a" * 32, "b" * 32, "c" * 32
    article_id, queue_key = "EASTMONEY:AN202610140001", "1" * 64
    target_date, cutoff = "20261016", "2026-10-16T14:57:00+08:00"
    authority_sha, capture_sha = "d" * 64, "e" * 64
    source_sha, body_sha, plan_sha, unit_map_sha, synth_input_sha = (
        "f" * 64, "0" * 64, "2" * 64, "3" * 64, "4" * 64)
    capture_ref = {"artifact_ref": f"products/{capture_sha}.json",
                   "owner": "v4.manager_workbench.capture_announcements",
                   "sha256": capture_sha, "source": "EASTMONEY_HK"}
    membership_gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
                       "status": "VERIFIED", "target_date": target_date, "cutoff": cutoff,
                       "authority_sha256": authority_sha}
    parent_hint = {"schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
                   "job_id": ancestor_id, "root_batch_job_id": root_id,
                   "input_sha256": "5" * 64, "result_sha256": "6" * 64,
                   "capture_product": {"artifact_ref": f"products/{'7' * 64}.json",
                                       "sha256": "7" * 64},
                   "target_date": target_date, "cutoff": cutoff,
                   "membership_authority_sha256": authority_sha}
    capture_identity = {
        "recovery_parent_job_id": parent_hint["job_id"],
        "recovery_parent_input_sha256": parent_hint["input_sha256"],
        "recovery_parent_result_sha256": parent_hint["result_sha256"],
        "capture_product_sha256": parent_hint["capture_product"]["sha256"],
        "target_date": target_date, "cutoff": cutoff,
    }
    recovery_lock = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
        "root_batch_job_id": root_id, "parent_job_id": ancestor_id,
        "parent_input_sha256": parent_hint["input_sha256"],
        "parent_result_sha256": parent_hint["result_sha256"],
        "parent_capture_product_sha256": parent_hint["capture_product"]["sha256"],
        "target_date": target_date, "cutoff": cutoff,
        "membership_authority_sha256": authority_sha, "capture_product_sha256": capture_sha,
        "eligible_count": 1,
    }
    input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                   "job_id": parent_id, "target_date": target_date, "cutoff": cutoff,
                   "capture_product": capture_ref, "membership_gate": membership_gate,
                   "recovery_lock": recovery_lock}
    input_raw = update_module._canonical(input_value)
    result = {
        "schema": "v4.manager_workbench.announcement_flash_result.v1",
        "job_id": parent_id, "target_trade_date": target_date,
        "state": "PARTIAL", "updated_at": "2026-10-16T20:10:36+00:00", "system_stop": None,
        "membership_gate": membership_gate,
        "counts": {"failed": 1, "queue_pending": 0, "context_pending": 0,
                   "membership_articles": {"in": 1},
                   "queue": {"failed": 1, "long_body_synthesis_pending": 0}},
        "failures": [
            {"article_id": article_id, "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
             "stage": "validator"},
            {"article_id": article_id, "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
             "status": "FAILED"},
        ],
        "long_body_processing": {"synthesis_prompt_token_cap": 160_000,
                                 "hard_prompt_token_cap": 160_000, "items": [{
            "article_id": article_id, "status": "SYNTHESIS_FAILED", "part_count": 2,
            "source_sha256": source_sha, "body_sha256": body_sha,
            "plan_sha256": plan_sha, "source_unit_map_sha256": unit_map_sha,
            "synthesis": {"status": "FAILED", "input_sha256": synth_input_sha,
                          "prompt_tokens_exact": 25},
        }]},
    }
    result_raw = update_module._canonical(result) + b"\n"
    progress = {"step": "DONE", "result_state": "PARTIAL",
                "updated_at": "2026-10-16T20:10:36.2+00:00"}
    progress_raw = update_module._canonical(progress) + b"\n"
    payload = {
        "queue_task_kind": "announcement_reader_synthesis",
        "role": "announcement_reader_synthesis", "article_id": article_id,
        "source_sha256": source_sha, "body_sha256": body_sha,
        "chunk_plan_sha256": plan_sha, "source_unit_map_sha256": unit_map_sha,
        "synthesis_input_sha256": synth_input_sha, "prompt_tokens_exact": 25,
        "prompt_token_cap": 160_000,
        "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
        "token_safety_margin": 1_024,
        "synthesis_input": {"article_id": article_id,
                            "synthesis_input_sha256": synth_input_sha, "part_count": 2},
    }
    payload_raw = update_module._canonical(payload)
    raw_response = b'{"saved":"raw response"}'
    payload_sha, raw_sha = update_module._sha(payload_raw), update_module._sha(raw_response)
    queue_job = {
        "status": "FAILED", "attempt_count": 1, "max_attempts": 1,
        "payload_sha256": payload_sha,
        "input_path": f"jobs/{queue_key}/input.json",
        "raw_path": f"jobs/{queue_key}/attempt-0001.raw", "raw_sha256": raw_sha,
        "validated_path": None, "validated_sha256": None,
        "attempts": [{"number": 1, "status": "FAILED",
                      "error": {"code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
                                "stage": "validator", "type": "ValidationRejected"},
                      "raw_path": f"jobs/{queue_key}/attempt-0001.raw", "raw_sha256": raw_sha,
                      "validated_path": None, "validated_sha256": None}],
    }
    queue_state_raw = update_module._canonical({"jobs": {queue_key: queue_job}}) + b"\n"
    svc.store.files.update({
        f"announcement_flash/jobs/{parent_id}/input.json": input_raw,
        f"announcement_flash/jobs/{parent_id}/progress.json": progress_raw,
        f"announcement_flash/jobs/{parent_id}/result.json": result_raw,
        "announcement_flash/queue/queue-state.json": queue_state_raw,
        f"announcement_flash/queue/jobs/{queue_key}/input.json": payload_raw,
        f"announcement_flash/queue/jobs/{queue_key}/attempt-0001.raw": raw_response,
    })
    result_sha = update_module._sha(result_raw)
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": parent_id, "target_date": target_date,
                   "result_sha256": result_sha}]
    }
    svc.store.values["announcement_flash_latest"] = {
        "job_id": parent_id, "target_date": target_date, "state": "RUNNING",
        "result_sha256": result_sha,
    }
    context = SimpleNamespace(
        target_date=target_date, cutoff=cutoff,
        scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                    "capture_input_sha256": update_module.digest(capture_identity),
                    "announcement_recovery_parent": parent_hint},
    )
    job = SimpleNamespace(job_id=parent_id, state=JobState.PARTIAL, step="DONE",
                          failed_steps=[], failure_code=None, context=context)
    svc.jobs.jobs[parent_id] = job
    svc.jobs._active = {}
    return svc, parent_id, queue_key, raw_sha


def _fixture_publish_result(svc, parent_id, result):
    raw = update_module._canonical(result) + b"\n"
    result_sha = update_module._sha(raw)
    svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"] = raw
    svc.store.values["announcement_flash_result_index"]["items"][0]["result_sha256"] = result_sha
    svc.store.values["announcement_flash_latest"]["result_sha256"] = result_sha


def _trace_only_fixture_result(svc, parent_id, queue_key, raw_sha):
    result = json.loads(svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"])
    row = json.loads(svc.store.files["announcement_flash/queue/queue-state.json"])["jobs"][queue_key]
    article_id = result["long_body_processing"]["items"][0]["article_id"]
    edits = [{"field": "counter_evidence", "citation_index": 0,
              "from_start_source_unit_id": "U000001", "from_end_source_unit_id": "U000001",
              "to_start_source_unit_id": article_id + "::U000001",
              "to_end_source_unit_id": article_id + "::U000001", "part_index": 1}]
    trace = {
        "status": "DERIVED_FROM_IMMUTABLE_FAILED_RAW",
        "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
        "source_idempotency_key": queue_key,
        "source_payload_sha256": row["payload_sha256"],
        "source_raw_path": row["raw_path"],
        "source_raw_sha256": raw_sha,
        "normalized_envelope_sha256": "8" * 64,
        "normalization_edits_sha256": update_module._sha(update_module._canonical(edits)),
        "normalization_edits": edits,
        "derived_validated_result_sha256": "9" * 64,
        "queue_status_preserved": "FAILED",
        "attempt_count_preserved": 1,
        "model_calls": 0,
    }
    item = result["long_body_processing"]["items"][0]
    item["status"] = "SAVED_RAW_RECOVERED_ORIGINAL_FAILURE_PRESERVED"
    item["synthesis"].update({"status": "FAILED", "validated_result_sha256": None,
                              "queue_validated_result_sha256": None,
                              "saved_raw_recovery": trace})
    result["failures"] = [row for row in result.get("failures", [])
                          if not isinstance(row, dict) or row.get("article_id") != article_id]
    result["failures"].append({"article_id": article_id,
                               "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
                               "stage": "validator", "status": "FAILED",
                               "resolution": "DERIVED_FROM_IMMUTABLE_SAVED_RAW"})
    result["saved_raw_recoveries"] = [{"article_id": article_id, **trace}]
    _fixture_publish_result(svc, parent_id, result)
    return result, trace


def test_manual_update_selects_only_indexed_terminal_saved_raw_synthesis_failure():
    svc, parent_id, queue_key, raw_sha = _saved_raw_citation_parent_fixture()
    update = AnnouncementUpdate(svc)

    parent = update._recovery_parent("20261016")

    assert parent is not None
    assert parent["job_id"] == parent_id
    queue_state = json.loads(svc.store.files["announcement_flash/queue/queue-state.json"])
    assert parent["saved_raw_recovery"] == {
        "schema": "v4.manager_workbench.announcement_flash_saved_raw_recovery_parent.v1",
        "article_id": "EASTMONEY:AN202610140001", "idempotency_key": queue_key,
        "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
        "payload_sha256": queue_state["jobs"][queue_key]["payload_sha256"],
        "raw_sha256": raw_sha, "synthesis_input_sha256": "4" * 64,
    }

    def reject(mutator):
        candidate, candidate_id, candidate_key, _ = _saved_raw_citation_parent_fixture()
        mutator(candidate, candidate_id, candidate_key)
        assert AnnouncementUpdate(candidate)._recovery_parent("20261016") is None

    reject(lambda candidate, _job, _key: setattr(candidate.jobs.jobs[_job], "state", JobState.RUNNING))
    reject(lambda candidate, _job, _key: candidate.jobs._active.update({"active": _job}))
    reject(lambda candidate, _job, _key: candidate.store.files.__setitem__(
        f"announcement_flash/jobs/{_job}/progress.json",
        update_module._canonical({"step": "RUNNING", "result_state": "PARTIAL",
                                  "updated_at": "2026-10-16T20:10:36.2+00:00"})))
    reject(lambda candidate, _job, key: candidate.store.files.__setitem__(
        f"announcement_flash/queue/jobs/{key}/attempt-0001.raw", b"tampered"))
    reject(lambda candidate, _job, _key: candidate.store.files.__setitem__(
        "announcement_flash/jobs/" + _job + "/result.json",
        update_module._canonical({**json.loads(candidate.store.files[
            "announcement_flash/jobs/" + _job + "/result.json"]),
            "saved_raw_recoveries": [{"status": "DERIVED_FROM_IMMUTABLE_FAILED_RAW"}]}) + b"\n"))


def test_manual_update_accepts_only_exact_trace_only_child_and_blocks_published_result_reentry():
    svc, parent_id, queue_key, raw_sha = _saved_raw_citation_parent_fixture()
    _trace_only_fixture_result(svc, parent_id, queue_key, raw_sha)

    parent = AnnouncementUpdate(svc)._recovery_parent("20261016")

    assert parent is not None
    assert parent["job_id"] == parent_id
    assert parent["saved_raw_recovery"]["idempotency_key"] == queue_key

    completed = json.loads(svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"])
    recovery_row = completed["saved_raw_recoveries"][0]
    recovery_row["publication_status"] = "VALIDATED_RESULT_INCLUDED_IN_RESULT_PAYLOAD"
    recovery_row["validated_result_sha256"] = recovery_row["derived_validated_result_sha256"]
    recovery_row["validated_result"] = {"results": [{"article_id": recovery_row["article_id"],
                                                        "reader_output": {"disposition": "NOT_SELECTED",
                                                                          "direction": "NEUTRAL"}}]}
    completed["long_body_processing"]["items"][0]["synthesis"].update({
        "status": "RECOVERED_FROM_SAVED_RAW",
        "validated_result_sha256": recovery_row["validated_result_sha256"],
    })
    completed.setdefault("provenance", {})["historical_outcomes"] = [{
        "article_id": recovery_row["article_id"], "source": "SAVED_RAW_RECOVERY",
        "status": "RECOVERED_NOT_SELECTED",
    }]
    _fixture_publish_result(svc, parent_id, completed)

    assert AnnouncementUpdate(svc)._recovery_parent("20261016") is None


def test_manual_update_recovery_click_uses_saved_raw_parent_and_active_job_stays_idempotent():
    svc, parent_id, _queue_key, _raw_sha = _saved_raw_citation_parent_fixture()
    update = AnnouncementUpdate(svc, clock=lambda: datetime(2026, 10, 17, 10, 0, tzinfo=HK))
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})

    assert response.status_code == 202, response.text
    assert len(svc.jobs.submissions) == 1
    context = svc.jobs.submissions[0][0]
    assert context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RECOVERY"
    assert context.scope_refs["announcement_recovery_parent"]["job_id"] == parent_id
    assert context.scope_refs["announcement_recovery_parent"]["saved_raw_recovery"][
        "failure_code"] == "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
    assert response.json()["data"]["job_id"] in svc.jobs.jobs
    assert svc.jobs.jobs[response.json()["data"]["job_id"]].context.cutoff == "2026-10-16T14:57:00+08:00"

    active_svc, active_id, _key, _sha = _saved_raw_citation_parent_fixture()
    active_svc.jobs.jobs[active_id].state = JobState.RUNNING
    active_svc.jobs._active = {"current": active_id}
    active = AnnouncementUpdate(active_svc, clock=lambda: datetime(2026, 10, 17, 10, 1, tzinfo=HK)).start(
        "20261016")
    assert active.job_id == active_id
    assert active_svc.jobs.submissions == []


def test_manual_update_recovers_original_batch_after_exact_failed_child():
    svc = service()
    parent_id = "f" * 32
    cutoff = "2026-10-16T14:57:00+08:00"
    now = datetime(2026, 10, 16, 15, 22, tzinfo=HK)
    authority_sha = "e" * 64
    capture_sha = "a" * 64
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
            "market": "HK_CONNECT", "authority_sha256": authority_sha, "codes": ["HK.12345"]}
    capture_ref = {"artifact_ref": f"products/{capture_sha}.json",
                   "owner": "v4.manager_workbench.capture_announcements",
                   "sha256": capture_sha, "source": "EASTMONEY_HK"}
    input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                   "job_id": parent_id, "target_date": "20261016", "cutoff": cutoff,
                   "capture_product": capture_ref,
                   "membership_gate": gate}
    input_raw = update_module._canonical(input_value)
    result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": parent_id,
              "target_trade_date": "20261016", "state": "PARTIAL", "system_stop": None,
              "membership_gate": {"status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
                                  "authority_sha256": authority_sha},
              "counts": {"queue_pending": 137, "context_pending": 2}}
    result_raw = update_module._canonical(result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{parent_id}/input.json"] = input_raw
    svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"] = result_raw
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": parent_id, "target_date": "20261016",
                   "result_sha256": update_module._sha(result_raw)}]
    }
    child_id = "1" * 32
    parent_hint = {"schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
                   "job_id": parent_id, "root_batch_job_id": parent_id,
                   "input_sha256": update_module._sha(input_raw),
                   "result_sha256": update_module._sha(result_raw),
                   "capture_product": {"artifact_ref": capture_ref["artifact_ref"],
                                       "sha256": capture_ref["sha256"]},
                   "target_date": "20261016", "cutoff": cutoff,
                   "membership_authority_sha256": authority_sha}
    capture_identity = {"recovery_parent_job_id": parent_id,
                        "recovery_parent_input_sha256": parent_hint["input_sha256"],
                        "recovery_parent_result_sha256": parent_hint["result_sha256"],
                        "capture_product_sha256": capture_sha,
                        "target_date": "20261016", "cutoff": cutoff}
    child_context = SimpleNamespace(
        target_date="20261016", cutoff=cutoff,
        scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                    "capture_input_sha256": update_module.digest(capture_identity),
                    "announcement_recovery_parent": parent_hint})
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    svc.jobs.jobs[child_id] = SimpleNamespace(
        job_id=child_id, state=JobState.FAILED, context=child_context,
        step="ACQUIRE_TEMPORARY_SOURCE_LEASE", failed_steps=["ACQUIRE_TEMPORARY_SOURCE_LEASE"],
        failure_code="RECOVERY_PARENT_IDENTITY_MISMATCH")

    job = AnnouncementUpdate(svc, clock=lambda: now).start("20261016")

    assert job.context.cutoff == cutoff
    assert job.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RECOVERY"
    recovery_parent = job.context.scope_refs["announcement_recovery_parent"]
    assert recovery_parent["job_id"] == parent_id
    assert recovery_parent["root_batch_job_id"] == parent_id
    assert recovery_parent["input_sha256"] == update_module._sha(input_raw)
    assert recovery_parent["result_sha256"] == update_module._sha(result_raw)
    assert recovery_parent["capture_product"] == capture_ref
    assert job.context.scope_refs["capture_input_sha256"] == update_module.digest(capture_identity)
    assert len(svc.jobs.submissions) == 1

    parent_hint["capture_product"]["source"] = "ALTERED_SOURCE"
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    later = datetime(2026, 10, 16, 15, 23, tzinfo=HK)
    rejected = AnnouncementUpdate(svc, clock=lambda: later).start("20261016")
    assert rejected.context.cutoff == later.isoformat()
    assert rejected.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert "announcement_recovery_parent" not in rejected.context.scope_refs
    assert len(svc.jobs.submissions) == 2

    parent_hint["capture_product"] = {"artifact_ref": "products/" + "b" * 64 + ".json",
                                      "sha256": capture_sha}
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    later_again = datetime(2026, 10, 16, 15, 24, tzinfo=HK)
    wrong_value = AnnouncementUpdate(svc, clock=lambda: later_again).start("20261016")
    assert wrong_value.context.cutoff == later_again.isoformat()
    assert wrong_value.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert "announcement_recovery_parent" not in wrong_value.context.scope_refs
    assert len(svc.jobs.submissions) == 3

    parent_hint["capture_product"] = capture_ref
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    later_full = datetime(2026, 10, 16, 15, 25, tzinfo=HK)
    complete_hint = AnnouncementUpdate(svc, clock=lambda: later_full).start("20261016")
    assert complete_hint.context.cutoff == cutoff
    assert complete_hint.context.scope_refs["announcement_recovery_parent"]["job_id"] == parent_id

    parent_hint["capture_product"] = {**capture_ref, "source": "ALTERED_SOURCE"}
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    later_tampered = datetime(2026, 10, 16, 15, 26, tzinfo=HK)
    tampered_full = AnnouncementUpdate(svc, clock=lambda: later_tampered).start("20261016")
    assert tampered_full.context.cutoff == later_tampered.isoformat()
    assert tampered_full.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert "announcement_recovery_parent" not in tampered_full.context.scope_refs


def _prequeue_body_binding_failure_fixture():
    svc = service()
    parent_id, child_id = "f" * 32, "1" * 32
    cutoff = "2026-10-16T14:57:00+08:00"
    authority_sha, parent_capture_sha = "e" * 64, "a" * 64
    child_capture_sha, body_sha = "b" * 64, "c" * 64
    article_id = "EASTMONEY:AN202610150001"
    current_bodies = {article_id: body_sha}
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
            "market": "HK_CONNECT", "authority_sha256": authority_sha, "codes": ["HK.12345"]}
    parent_capture_ref = {"artifact_ref": f"products/{parent_capture_sha}.json",
                          "owner": "v4.manager_workbench.capture_announcements",
                          "sha256": parent_capture_sha, "source": "EASTMONEY_HK"}
    legacy_parent_capture_ref = {"artifact_ref": parent_capture_ref["artifact_ref"],
                                 "sha256": parent_capture_sha}
    parent_input = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                    "job_id": parent_id, "target_date": "20261016", "cutoff": cutoff,
                    "capture_product": parent_capture_ref, "membership_gate": gate}
    parent_input_raw = update_module._canonical(parent_input)
    parent_result = {"schema": "v4.manager_workbench.announcement_flash_result.v1",
                     "job_id": parent_id, "target_trade_date": "20261016", "state": "PARTIAL",
                     "system_stop": None,
                     "membership_gate": {"status": "VERIFIED", "target_date": "20261016",
                                         "cutoff": cutoff, "authority_sha256": authority_sha},
                     "counts": {"queue_pending": 137, "context_pending": 2}}
    parent_result_raw = update_module._canonical(parent_result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{parent_id}/input.json"] = parent_input_raw
    svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"] = parent_result_raw
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": parent_id, "target_date": "20261016",
                   "result_sha256": update_module._sha(parent_result_raw)}]
    }
    parent_hint = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
        "job_id": parent_id, "root_batch_job_id": parent_id,
        "input_sha256": update_module._sha(parent_input_raw),
        "result_sha256": update_module._sha(parent_result_raw),
        "capture_product": legacy_parent_capture_ref,
        "target_date": "20261016", "cutoff": cutoff,
        "membership_authority_sha256": authority_sha,
    }
    capture_identity = {
        "recovery_parent_job_id": parent_id,
        "recovery_parent_input_sha256": parent_hint["input_sha256"],
        "recovery_parent_result_sha256": parent_hint["result_sha256"],
        "capture_product_sha256": parent_capture_sha,
        "target_date": "20261016", "cutoff": cutoff,
    }
    child_input = {
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": child_id, "target_date": "20261016", "cutoff": cutoff,
        "capture_product": {"artifact_ref": f"products/{child_capture_sha}.json",
                            "owner": "v4.manager_workbench.capture_announcements",
                            "sha256": child_capture_sha, "source": "EASTMONEY_HK"},
        "membership_gate": gate,
        "recovery_lock": {
            "schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
            "root_batch_job_id": parent_id, "parent_job_id": parent_id,
            "parent_input_sha256": parent_hint["input_sha256"],
            "parent_result_sha256": parent_hint["result_sha256"],
            "parent_capture_product_sha256": parent_capture_sha,
            "target_date": "20261016", "cutoff": cutoff,
            "membership_authority_sha256": authority_sha,
            "capture_product_sha256": child_capture_sha,
            "row_count": 1, "article_ids_sha256": "1" * 64,
            "row_manifest_sha256": "2" * 64,
            "eligible_article_ids": [article_id], "eligible_article_ids_sha256": "3" * 64,
            "eligible_count": 1, "expected_body_sha256": dict(current_bodies),
            "eligible_missing_body_article_ids": [],
            "current_body_sha256": dict(current_bodies),
            "current_body_sha256_digest": update_module.digest(current_bodies),
        },
    }
    svc.store.files[f"announcement_flash/jobs/{child_id}/input.json"] = update_module._canonical(child_input)
    svc.store.files[f"announcement_flash/jobs/{child_id}/progress.json"] = update_module._canonical({
        "step": "FAILED", "failure_code": "RECOVERY_BODY_BINDING_INVALID"})
    child_context = SimpleNamespace(
        target_date="20261016", cutoff=cutoff,
        scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                    "capture_input_sha256": update_module.digest(capture_identity),
                    "announcement_recovery_parent": parent_hint})
    svc.store.values["announcement_flash_latest"] = {"job_id": child_id, "target_date": "20261016"}
    svc.jobs.jobs[child_id] = SimpleNamespace(
        job_id=child_id, state=JobState.FAILED, context=child_context,
        step="FLASH_SELECTION", failed_steps=["FLASH_SELECTION"],
        failure_code="RECOVERY_BODY_BINDING_INVALID")
    return svc, child_id, child_input, parent_hint


def test_manual_update_recovers_original_batch_after_prequeue_body_binding_failure():
    svc, _child_id, _child_input, parent_hint = _prequeue_body_binding_failure_fixture()
    resolved = AnnouncementUpdate(svc)._recovery_parent("20261016")
    assert resolved is not None
    assert resolved["job_id"] == "f" * 32
    assert resolved["root_batch_job_id"] == parent_hint["root_batch_job_id"]
    assert resolved["input_sha256"] == parent_hint["input_sha256"]
    assert resolved["result_sha256"] == parent_hint["result_sha256"]
    assert resolved["capture_product"]["sha256"] == "a" * 64
    assert svc.jobs.submissions == []

    def fail_different_stage(svc, child_id, _input):
        svc.jobs.jobs[child_id].step = "QUEUE_PROCESS"
        svc.jobs.jobs[child_id].failed_steps = ["QUEUE_PROCESS"]

    def fail_different_code(svc, child_id, _input):
        svc.jobs.jobs[child_id].failure_code = "FLASH_PIPELINE_RUNTIMEERROR"

    def fail_different_progress(_svc, child_id, _input):
        _svc.store.files[f"announcement_flash/jobs/{child_id}/progress.json"] = update_module._canonical({
            "step": "FAILED", "failure_code": "FLASH_PIPELINE_RUNTIMEERROR"})

    def add_result(svc, child_id, _input):
        svc.store.files[f"announcement_flash/jobs/{child_id}/result.json"] = b"{}"

    def change_parent_hash(_svc, _child_id, child_input):
        child_input["recovery_lock"]["parent_result_sha256"] = "9" * 64

    def change_body_hash(_svc, _child_id, child_input):
        lock = child_input["recovery_lock"]
        article_id = lock["eligible_article_ids"][0]
        lock["current_body_sha256"][article_id] = "9" * 64
        lock["current_body_sha256_digest"] = update_module.digest(lock["current_body_sha256"])

    def change_body_digest(_svc, _child_id, child_input):
        child_input["recovery_lock"]["current_body_sha256_digest"] = "9" * 64

    def change_cutoff(_svc, _child_id, child_input):
        child_input["cutoff"] = "2026-10-16T15:00:00+08:00"

    def change_capture_hash(_svc, _child_id, child_input):
        child_input["capture_product"]["sha256"] = "9" * 64

    for mutate in (fail_different_stage, fail_different_code, fail_different_progress, add_result,
                   change_parent_hash, change_body_hash, change_body_digest, change_cutoff,
                   change_capture_hash):
        candidate, child_id, child_input, _hint = _prequeue_body_binding_failure_fixture()
        mutate(candidate, child_id, child_input)
        candidate.store.files[f"announcement_flash/jobs/{child_id}/input.json"] = update_module._canonical(
            child_input)
        assert AnnouncementUpdate(candidate)._recovery_parent("20261016") is None


def test_manual_update_does_not_auto_resume_partial_batch_after_system_stop():
    svc = service()
    parent_id = "9" * 32
    cutoff = "2026-10-16T14:57:00+08:00"
    now = datetime(2026, 10, 16, 15, 22, tzinfo=HK)
    authority_sha = "e" * 64
    capture_sha = "a" * 64
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
            "market": "HK_CONNECT", "authority_sha256": authority_sha, "codes": ["HK.12345"]}
    input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                   "job_id": parent_id, "target_date": "20261016", "cutoff": cutoff,
                   "capture_product": {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha},
                   "membership_gate": gate}
    input_raw = update_module._canonical(input_value)
    result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": parent_id,
              "target_trade_date": "20261016", "state": "PARTIAL",
              "system_stop": {"failure_code": "TransportError"},
              "membership_gate": {"status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
                                  "authority_sha256": authority_sha},
              "counts": {"queue_pending": 137, "context_pending": 0}}
    result_raw = update_module._canonical(result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{parent_id}/input.json"] = input_raw
    svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"] = result_raw
    svc.store.values["announcement_flash_latest"] = {"job_id": parent_id, "target_date": "20261016"}
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": parent_id, "target_date": "20261016",
                   "result_sha256": update_module._sha(result_raw)}]
    }
    svc.jobs.jobs[parent_id] = SimpleNamespace(job_id=parent_id, state=JobState.PARTIAL,
                                               context=SimpleNamespace(target_date="20261016"))

    job = AnnouncementUpdate(svc, clock=lambda: now).start("20261016")

    assert job.context.cutoff == now.isoformat()
    assert job.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert "announcement_recovery_parent" not in job.context.scope_refs


def test_workbench_recovery_worker_recaptures_and_launches_bound_pending_continuation(monkeypatch):
    svc = service()
    svc.config.shared_root = "/private/shared"
    parent_id = "8" * 32
    job_id = "7" * 32
    cutoff = "2026-10-16T14:57:00+08:00"
    authority_sha = "e" * 64
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
            "market": "HK_CONNECT", "owner": "test", "authority_sha256": authority_sha,
            "authority_version": "v1", "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59+08:00", "member_count": 1,
            "members_sha256": "f" * 64, "codes": ["HK.12345"]}
    body = "冻结公告正文。"
    body_sha = update_module._sha(body.encode("utf-8"))
    raw_row = {"art_code": "AN202610150001", "title": "测试公告", "notice_date": "2026-10-15 10:00:00",
               "display_time": "2026-10-15 10:00:00", "codes": [{"stock_code": "12345", "market_code": "116",
               "ann_type": "H", "short_name": "测试公司"}]}
    row = {"art_code": raw_row["art_code"], "title": "测试公告", "publication_date": "2026-10-15",
           "display_time": "2026-10-15T10:00:00+08:00", "source_issuer_codes": [
               {"code": "HK.12345", "source_stock_code": "12345", "market_code": "116",
                "ann_type": "H", "name": "测试公司"}], "raw_row": raw_row,
           "window_consumption_status": "ELIGIBLE_SOURCE_TIME",
           "listing_source_ref": {"sha256": "c" * 64}, "body_complete": True,
           "body_text": body, "body_text_sha256": body_sha, "content_page_count": 1,
           "pages": [{"page_number": 1, "page_total": 1, "text": body, "text_sha256": body_sha,
                      "source_ref": {"available_at": "2026-10-16T14:50:00+08:00",
                                     "reused_from": {"request_sha256": "b" * 64}}}]}
    old_product = {"schema_version": "mwb.capture.window.v1", "owner": "v4.manager_workbench.capture_announcements",
                   "source": "EASTMONEY_HK", "target_trade_date": "20261016",
                   "window": {"research_cutoff": cutoff}, "rows": [row]}
    current_product = {**old_product}
    old_raw = update_module._canonical(old_product)
    current_raw = update_module._canonical(current_product)
    old_sha = update_module._sha(old_raw)
    current_sha = update_module._sha(current_raw)
    old_ref = {"artifact_ref": f"products/{old_sha}.json",
               "owner": "v4.manager_workbench.capture_announcements",
               "sha256": old_sha, "source": "EASTMONEY_HK"}
    current_ref = {"artifact_ref": f"products/{current_sha}.json",
                   "owner": "v4.manager_workbench.capture_announcements",
                   "sha256": current_sha, "source": "EASTMONEY_HK"}
    parent_input = {"schema": "v4.manager_workbench.announcement_flash_input.v1", "job_id": parent_id,
                    "target_date": "20261016", "cutoff": cutoff, "capture_product": old_ref,
                    "membership_gate": gate}
    parent_input_raw = update_module._canonical(parent_input)
    parent_result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": parent_id,
                     "target_trade_date": "20261016", "state": "PARTIAL", "system_stop": None,
                     "membership_gate": {key: gate[key] for key in (
                         "status", "target_date", "cutoff", "market", "owner", "authority_sha256",
                         "authority_version", "effective_from", "effective_to", "available_at", "member_count")},
                     "counts": {"queue_pending": 1, "context_pending": 0}}
    parent_result_raw = update_module._canonical(parent_result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{parent_id}/input.json"] = parent_input_raw
    svc.store.files[f"announcement_flash/jobs/{parent_id}/result.json"] = parent_result_raw
    source_refs = {old_ref["artifact_ref"]: old_raw, current_ref["artifact_ref"]: current_raw}
    command_calls = []

    class FakeCaptureStore:
        def __init__(self, *_args, **_kwargs):
            self.io = SimpleNamespace(read_bytes=lambda ref, **_opts: source_refs[ref])

        def grant(self, **_kwargs):
            pass

        def revoke(self):
            pass

    class FinishedProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    def fake_popen(command, **kwargs):
        command_calls.append((command, kwargs))
        return FinishedProcess()

    def fake_capture(_context, _request, _store):
        return {"saved_ref": current_ref}

    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore", FakeCaptureStore)
    monkeypatch.setattr("v4.manager_workbench.inputs.capture.capture_window", fake_capture)
    monkeypatch.setattr("v4.manager_workbench.announcement_membership.revalidate_membership_gate",
                        lambda *_args: dict(gate))
    svc.jobs = SimpleNamespace(update=lambda *_args, **_kwargs: None)
    recovery_parent = {"schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
                       "job_id": parent_id, "root_batch_job_id": parent_id,
                       "input_sha256": update_module._sha(parent_input_raw),
                       "result_sha256": update_module._sha(parent_result_raw),
                       "capture_product": old_ref, "target_date": "20261016", "cutoff": cutoff,
                       "membership_authority_sha256": authority_sha}
    context = SimpleNamespace(target_date="20261016", cutoff=cutoff,
                              scope_refs={"announcement_recovery_parent": recovery_parent},
                              model_copy=lambda **_kwargs: context)
    job = SimpleNamespace(job_id=job_id, context=context, completed_count=0, total_count=None,
                          execution_refs=[])

    try:
        AnnouncementUpdate(svc, popen=fake_popen)._work(job)
    except update_module.StepFailure as exc:
        assert str(exc) == "FLASH_RESULT_INVALID"
    else:
        raise AssertionError("missing runner result must stop after automatic launch")

    command, kwargs = command_calls[0]
    assert "--resume-pending" in command
    assert command[command.index("--job-id") + 1] == job_id
    assert command[command.index("--shared-root") + 1] == "/private/shared"
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    stored_input = json.loads(svc.store.files[f"announcement_flash/jobs/{job_id}/input.json"])
    lock = stored_input["recovery_lock"]
    assert stored_input["cutoff"] == cutoff
    assert stored_input["capture_product"] == current_ref
    assert lock["root_batch_job_id"] == parent_id
    assert lock["parent_result_sha256"] == recovery_parent["result_sha256"]
    assert lock["eligible_count"] == 1
    assert lock["eligible_article_ids"] == ["EASTMONEY:AN202610150001"]

    tampered_parent = {**recovery_parent,
                       "capture_product": {**old_ref, "source": "OTHER_SOURCE"}}
    tampered_capture_store = SimpleNamespace(
        io=SimpleNamespace(read_bytes=lambda ref, **_opts: source_refs[ref]))
    try:
        AnnouncementUpdate(svc)._prepare_recovery_lock(job, tampered_parent, tampered_capture_store)
    except update_module.StepFailure as exc:
        assert str(exc) == "RECOVERY_PARENT_IDENTITY_MISMATCH"
    else:
        raise AssertionError("tampered capture-product metadata must not bind to the original batch")


def test_manual_update_rejects_a_different_target_while_job_is_active():
    svc = service()
    now = datetime(2026, 10, 16, 10, 30, tzinfo=HK)
    update = AnnouncementUpdate(svc, clock=lambda: now)
    active = update.start("20261015")

    try:
        update.start("20261016")
    except update_module.JobConflict as exc:
        assert "20261015" in str(exc)
    else:
        raise AssertionError("active job for another target date must not be accepted")

    assert active.state == JobState.QUEUED
    assert len(svc.jobs.submissions) == 1


def test_http_post_uses_the_announcement_route_and_never_codex_runs(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 31, tzinfo=HK)
    original = api.AnnouncementUpdate

    class FixedClockUpdate(original):
        def __init__(self, service_arg):
            super().__init__(service_arg, clock=lambda: now)

    monkeypatch.setattr(api, "AnnouncementUpdate", FixedClockUpdate)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    client = TestClient(app)
    response = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261016"})

    assert response.status_code == 202
    assert response.json()["data"]["target_date"] == "20261016"
    assert len(svc.jobs.submissions) == 1
    readback = client.get(api.PREFIX + "/announcement-flash?target_date=20261016")
    assert readback.status_code == 200, readback.text
    assert len(svc.jobs.submissions) == 1


def test_http_post_rejects_cross_date_active_job_with_conflict(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 32, tzinfo=HK)
    original = api.AnnouncementUpdate

    class FixedClockUpdate(original):
        def __init__(self, service_arg):
            super().__init__(service_arg, clock=lambda: now)

    monkeypatch.setattr(api, "AnnouncementUpdate", FixedClockUpdate)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    client = TestClient(app)
    active = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261015"})
    assert active.status_code == 202

    rejected = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261016"})

    assert rejected.status_code == 409
    assert "20261015" in str(rejected.json())
    assert len(svc.jobs.submissions) == 1


def test_incremental_result_round_trips_through_get_with_new_reason(monkeypatch):
    svc = service()
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": "2026-10-16T10:00:00+08:00", "market": "HK_CONNECT",
            "owner": "v35_dispatcher.research_panel_daily_hk", "authority_sha256": "e" * 64,
            "authority_version": "version", "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59.501065+08:00", "member_count": 1,
            "codes": ["HK.12345"]}
    monkeypatch.setattr("v4.manager_workbench.announcement_membership.resolve_membership_gate",
                        lambda *_args: dict(gate))
    job_id = "a" * 32
    article = {"article_id": "EASTMONEY:AN202610160099", "title": "新公告", "publication_date": "2026-10-16",
               "symbol": "HK.12345", "name": "新公司", "disposition": "SELECTED_EVENT", "direction": "POSITIVE",
               "selection_basis": "新增事件信息", "reason": "公司披露新增业务安排，具体影响需人工核实。", "impact": [],
               "body_sha256": "1" * 64, "source_sha256": "2" * 64, "source_origins": [],
               "review_status": "MODEL_CANDIDATE_UNREVIEWED", "reuse_status": None}
    result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": job_id,
              "state": "PARTIAL", "target_trade_date": "20261016", "updated_at": "2026-10-16T10:00:00+08:00",
              "counts": {"new_candidate_stocks": 1, "failed": 0, "queue_pending": 0, "body_gaps": 0},
              "stocks": [{"symbol": article["symbol"], "name": article["name"], "reasons": [article["reason"]],
                          "articles": [article], "review_status": article["review_status"], "reuse_status": None}],
              "failures": [], "pending": [], "gaps": [],
              "provenance": {"historical_outcomes": []}}
    raw = update_module._canonical(result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"] = raw
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": job_id, "target_date": "20261016", "result_sha256": update_module._sha(raw)}]
    }

    view = AnnouncementUpdate(svc).read("20261016")

    assert view["target_trade_date"] == "20261016"
    assert view["membership"]["target_date"] == "20261016"
    assert view["incremental"]["job_id"] == job_id
    assert view["incremental"]["target_trade_date"] == "20261016"
    assert view["incremental"]["stocks"][0]["articles"][0]["reason"] == article["reason"]
    assert any(stock["symbol"] == "HK.12345" and article["reason"] in stock["reasons"]
               for stock in view["stocks"] for article in stock["articles"])
    assert view["counts"]["displayed_stocks"] == 1


def _saved_r8_identity_conflict_case():
    """Load immutable live descriptors into an isolated fake service for R8b."""
    import hashlib
    from pathlib import Path
    import pytest

    batch = Path("/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/evidence/announcement-workbench-20261016/batch-recovery-1457")
    review_path = batch / "review/live-r6-terminal-review.json"
    config_path = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-recovery-v2r1-20261016-r2.json")
    if not review_path.is_file() or not config_path.is_file():
        pytest.skip("R8_SAVED_SERVICE_DESCRIPTORS_UNAVAILABLE")
    review_raw = review_path.read_bytes()
    assert hashlib.sha256(review_raw).hexdigest() == "22b9f08df4678ba818226bdb6212edf1a5eabcdb793d93622fa5511a2e73cfe0"
    review = json.loads(review_raw)
    evidence = review["evidence"]
    job_id = "85add37723bf4c5ea1445dcb61202899"
    expected_hashes = {
        "input.json": "93f92c171864402837b68c2632e8dd0c49a6ef5a7d14d52d324b7f554a357b3a",
        "progress.json": "4718d645f94059c34b6e6e9fb87e6de2e11be4c40025ee2de5ae645e4f18b9cb",
        "result.json": "5d14c4f444fda0cffac5ea5c08390363ad6dbc8aee64498e022f70bffb8e7cf0",
    }
    job_root = Path(evidence["job_input"]["path"]).parent
    source_files = {name: (job_root / name).read_bytes() for name in expected_hashes}
    for name, expected in expected_hashes.items():
        assert hashlib.sha256(source_files[name]).hexdigest() == expected
    assert hashlib.sha256(source_files["input.json"]).hexdigest() == evidence["job_input"]["sha256"]
    assert hashlib.sha256(source_files["progress.json"]).hexdigest() == evidence["job_progress"]["sha256"]
    assert hashlib.sha256(source_files["result.json"]).hexdigest() == expected_hashes["result.json"]
    input_value = json.loads(source_files["input.json"])
    progress = json.loads(source_files["progress.json"])
    result = json.loads(source_files["result.json"])
    lock = input_value["recovery_lock"]
    assert input_value["job_id"] == job_id
    assert lock["root_batch_job_id"] == "87ff9d4b89d841ccb36c5c1b01046171"
    assert lock["parent_job_id"] == "b1c877411e02407990f1774bc72dd1c6"
    assert result["system_stop"]["failure_code"] == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
    assert progress["failure_code"] == result["system_stop"]["failure_code"]

    flash_root = job_root.parent.parent
    state_root = flash_root.parent
    latest_path = state_root / "cursors/announcement_flash_latest.json"
    index_path = state_root / "cursors/announcement_flash_result_index.json"
    latest_raw, index_raw = latest_path.read_bytes(), index_path.read_bytes()
    latest, result_index = json.loads(latest_raw), json.loads(index_raw)
    result_sha = hashlib.sha256(source_files["result.json"]).hexdigest()
    assert latest == {"job_id": job_id, "result_sha256": result_sha, "result_state": "PARTIAL",
                      "slot": "2026-10-16T20:15:00+08:00", "state": "FAILED", "target_date": "20261016"}
    assert any(item.get("job_id") == job_id and item.get("target_date") == "20261016"
               and item.get("result_sha256") == result_sha for item in result_index["items"])

    manager_files = {}
    snapshots = {str(latest_path): hashlib.sha256(latest_raw).hexdigest(),
                 str(index_path): hashlib.sha256(index_raw).hexdigest()}
    for saved_id in {job_id, lock["parent_job_id"], lock["root_batch_job_id"]}:
        saved_dir = flash_root / "jobs" / lineage_cursor
        for name in ("input.json", "result.json", "progress.json"):
            path = saved_dir / name
            if path.is_file():
                raw = path.read_bytes()
                manager_files[f"announcement_flash/jobs/{saved_id}/{name}"] = raw
                snapshots[str(path)] = hashlib.sha256(raw).hexdigest()
    capture_config = json.loads(config_path.read_text())
    capture_root = Path(capture_config["capture_root"])
    capture_path = capture_root / input_value["capture_product"]["artifact_ref"]
    capture_raw = capture_path.read_bytes()
    assert hashlib.sha256(capture_raw).hexdigest() == input_value["capture_product"]["sha256"]
    capture_value = json.loads(capture_raw)
    snapshots[str(capture_path)] = hashlib.sha256(capture_raw).hexdigest()

    svc = service()
    from v4.manager_workbench.config import load_config
    svc.config = load_config(config_path)
    svc.store.files.update(manager_files)
    svc.store.values["announcement_flash_latest"] = latest
    svc.store.values["announcement_flash_result_index"] = result_index

    # Preserve the actual immediately preceding B1 parent hint in the saved
    # job context; the next click must bind to 85 itself, while retaining root 87ff.
    parent_input_raw = manager_files[f"announcement_flash/jobs/{lock['parent_job_id']}/input.json"]
    parent_input = json.loads(parent_input_raw)
    parent_hint = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
        "job_id": lock["parent_job_id"], "root_batch_job_id": lock["root_batch_job_id"],
        "input_sha256": lock["parent_input_sha256"], "result_sha256": lock["parent_result_sha256"],
        "capture_product": parent_input["capture_product"], "target_date": input_value["target_date"],
        "cutoff": input_value["cutoff"],
        "membership_authority_sha256": input_value["membership_gate"]["authority_sha256"],
    }
    capture_identity = {"recovery_parent_job_id": parent_hint["job_id"],
                        "recovery_parent_input_sha256": parent_hint["input_sha256"],
                        "recovery_parent_result_sha256": parent_hint["result_sha256"],
                        "capture_product_sha256": parent_hint["capture_product"]["sha256"],
                        "target_date": input_value["target_date"], "cutoff": input_value["cutoff"]}
    context = SimpleNamespace(target_date=input_value["target_date"], cutoff=input_value["cutoff"],
                              scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                                          "capture_input_sha256": update_module.digest(capture_identity),
                                          "announcement_recovery_parent": parent_hint})
    terminal = review["job_terminal"]
    svc.jobs.jobs[job_id] = SimpleNamespace(
        job_id=job_id, state=JobState.FAILED, context=context, step=terminal["step"],
        failed_steps=[terminal["step"]], failure_code=terminal["failure_code"])
    return {"service": svc, "review": review, "input": input_value, "progress": progress,
            "result": result, "result_raw": source_files["result.json"], "result_sha": result_sha,
            "capture_ref": input_value["capture_product"], "capture_raw": capture_raw,
            "capture": capture_value, "snapshots": snapshots}


def _saved_r8c_zero_candidate_case():
    """Bind the saved 804 queue-stop state into a fake service without changing source artifacts."""
    import hashlib
    from pathlib import Path
    import pytest

    batch = Path("/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/evidence/announcement-workbench-20261016/batch-recovery-1457")
    review_path = batch / "review/r8c-live-admission.json"
    config_path = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-recovery-v2r1-20261016-r2.json")
    if not review_path.is_file() or not config_path.is_file():
        pytest.skip("R8C_SAVED_SERVICE_DESCRIPTORS_UNAVAILABLE")
    review_raw = review_path.read_bytes()
    assert hashlib.sha256(review_raw).hexdigest() == "218554a40b6649d2c28e885973021d204c7f25047b67496a2fc5261cfa5eea22"
    review = json.loads(review_raw)
    job_id = review["actual_run"]["job_id"]
    assert job_id == "804217cd924d421fabca45c5c7b9d834"
    from v4.manager_workbench.config import load_config
    config = load_config(config_path)
    state_root = Path(config.state_root) / "manager_workbench"
    flash_root = state_root / "announcement_flash"
    job_root = flash_root / "jobs" / job_id
    expected = {"input.json": review["actual_run"]["input_sha256"],
                "progress.json": review["actual_run"]["progress_sha256"],
                "result.json": review["actual_run"]["result_sha256"]}
    source_files = {name: (job_root / name).read_bytes() for name in expected}
    for name, sha256 in expected.items():
        assert hashlib.sha256(source_files[name]).hexdigest() == sha256
    input_value, progress, result = (json.loads(source_files["input.json"]),
                                     json.loads(source_files["progress.json"]),
                                     json.loads(source_files["result.json"]))
    assert input_value["job_id"] == job_id
    assert progress["step"] == "FAILED"
    assert progress["failure_code"] == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
    assert result["state"] == "PARTIAL"
    assert result["counts"]["new_candidate_stocks"] == 0
    assert result["system_stop"]["failure_code"] == progress["failure_code"]
    lock = input_value["recovery_lock"]
    assert lock["root_batch_job_id"] == "87ff9d4b89d841ccb36c5c1b01046171"
    assert lock["parent_job_id"] == "85add37723bf4c5ea1445dcb61202899"
    target_date, cutoff = input_value["target_date"], input_value["cutoff"]

    latest_path = state_root / "cursors/announcement_flash_latest.json"
    index_path = state_root / "cursors/announcement_flash_result_index.json"
    latest_raw, index_raw = latest_path.read_bytes(), index_path.read_bytes()
    latest, result_index = json.loads(latest_raw), json.loads(index_raw)
    result_sha = hashlib.sha256(source_files["result.json"]).hexdigest()
    assert latest.get("job_id") == job_id and latest.get("target_date") == target_date
    assert latest.get("state") == "FAILED" and latest.get("result_state") == "PARTIAL"
    assert latest.get("result_sha256") == result_sha
    assert any(item.get("job_id") == job_id and item.get("target_date") == target_date
               and item.get("result_sha256") == result_sha for item in result_index["items"])

    parent_id, root_id = lock["parent_job_id"], lock["root_batch_job_id"]
    manager_files = {}
    snapshots = {str(latest_path): hashlib.sha256(latest_raw).hexdigest(),
                 str(index_path): hashlib.sha256(index_raw).hexdigest()}
    saved_ids = set()
    lineage_cursor = job_id
    for _depth in range(16):
        if lineage_cursor in saved_ids:
            break
        saved_ids.add(lineage_cursor)
        saved_dir = flash_root / "jobs" / lineage_cursor
        for name in ("input.json", "result.json", "progress.json"):
            path = saved_dir / name
            if path.is_file():
                raw = path.read_bytes()
                manager_files[f"announcement_flash/jobs/{lineage_cursor}/{name}"] = raw
                snapshots[str(path)] = hashlib.sha256(raw).hexdigest()
        lineage_input = json.loads((saved_dir / "input.json").read_bytes())
        if lineage_cursor == root_id:
            break
        lineage_lock = lineage_input.get("recovery_lock") if isinstance(lineage_input, dict) else None
        if not isinstance(lineage_lock, dict) or not isinstance(lineage_lock.get("parent_job_id"), str):
            break
        lineage_cursor = lineage_lock["parent_job_id"]
    parent_input = json.loads(manager_files[f"announcement_flash/jobs/{parent_id}/input.json"])
    parent_hint = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
        "job_id": parent_id, "root_batch_job_id": root_id,
        "input_sha256": lock["parent_input_sha256"],
        "result_sha256": lock["parent_result_sha256"],
        "capture_product": parent_input["capture_product"],
        "target_date": target_date, "cutoff": cutoff,
        "membership_authority_sha256": lock["membership_authority_sha256"],
    }
    capture_identity = {"recovery_parent_job_id": parent_hint["job_id"],
                        "recovery_parent_input_sha256": parent_hint["input_sha256"],
                        "recovery_parent_result_sha256": parent_hint["result_sha256"],
                        "capture_product_sha256": parent_hint["capture_product"]["sha256"],
                        "target_date": target_date, "cutoff": cutoff}
    context = SimpleNamespace(target_date=target_date, cutoff=cutoff,
                              scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                                          "capture_input_sha256": update_module.digest(capture_identity),
                                          "announcement_recovery_parent": parent_hint})
    svc = service()
    svc.config = config
    svc.store.files.update(manager_files)
    svc.store.values["announcement_flash_latest"] = latest
    svc.store.values["announcement_flash_result_index"] = result_index
    svc.jobs.jobs[job_id] = SimpleNamespace(
        job_id=job_id, state=JobState.FAILED, context=context,
        step=review["actual_run"]["step"], failed_steps=[review["actual_run"]["step"]],
        failure_code=progress["failure_code"], finished_at=progress.get("updated_at"),
    )
    capture_root = Path(config.capture_root)
    capture_ref = input_value["capture_product"]
    capture_path = capture_root / capture_ref["artifact_ref"]
    capture_raw = capture_path.read_bytes()
    assert hashlib.sha256(capture_raw).hexdigest() == capture_ref["sha256"]
    capture_value = json.loads(capture_raw)
    snapshots[str(capture_path)] = hashlib.sha256(capture_raw).hexdigest()
    return {"service": svc, "review": review, "input": input_value, "progress": progress,
            "result": result, "result_sha": result_sha, "capture_ref": capture_ref,
            "capture_raw": capture_raw, "capture": capture_value, "snapshots": snapshots}


def test_http_date_only_continues_saved_804_zero_candidate_queue_stop_with_frozen_cutoff():
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    case = _saved_r8c_zero_candidate_case()
    svc = case["service"]
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})
    assert response.status_code == 202, response.text
    assert len(svc.jobs.submissions) == 1
    child = next(job for job_id, job in svc.jobs.jobs.items() if job_id != case["input"]["job_id"])
    assert child.context.cutoff == case["input"]["cutoff"]
    parent = child.context.scope_refs["announcement_recovery_parent"]
    assert parent["job_id"] == case["input"]["job_id"]
    assert parent["root_batch_job_id"] == case["input"]["recovery_lock"]["root_batch_job_id"]
    assert parent.get("recoverable_system_stop_code") == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"

    capture_store = SimpleNamespace(io=SimpleNamespace(
        read_bytes=lambda ref, **_kwargs: case["capture_raw"] if ref == case["capture_ref"]["artifact_ref"]
        else (_ for _ in ()).throw(FileNotFoundError(ref))))
    next_lock, fresh_gate = AnnouncementUpdate(svc)._prepare_recovery_lock(
        child, parent, capture_store)
    old_lock = case["input"]["recovery_lock"]
    assert next_lock["parent_job_id"] == case["input"]["job_id"]
    assert next_lock["root_batch_job_id"] == old_lock["root_batch_job_id"]
    assert next_lock["cutoff"] == old_lock["cutoff"]
    assert next_lock["membership_authority_sha256"] == old_lock["membership_authority_sha256"]
    assert next_lock["row_manifest_sha256"] == old_lock["row_manifest_sha256"]
    assert next_lock["eligible_article_ids_sha256"] == old_lock["eligible_article_ids_sha256"]
    assert next_lock["expected_body_sha256"] == old_lock["current_body_sha256"]
    assert fresh_gate["authority_sha256"] == old_lock["membership_authority_sha256"]
    for path, before_sha in case["snapshots"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before_sha


def test_http_date_only_rejects_negative_candidate_count_for_queue_stop():
    case = _saved_r8c_zero_candidate_case()
    svc = case["service"]
    result = dict(case["result"])
    result["counts"] = dict(result["counts"])
    result["counts"]["new_candidate_stocks"] = -1
    result_raw = update_module._canonical(result) + b"\n"
    result_sha = update_module._sha(result_raw)
    job_id = case["input"]["job_id"]
    svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"] = result_raw
    latest = dict(svc.store.values["announcement_flash_latest"], result_sha256=result_sha)
    svc.store.values["announcement_flash_latest"] = latest
    index = dict(svc.store.values["announcement_flash_result_index"])
    index["items"] = [dict(item, result_sha256=result_sha) if item.get("job_id") == job_id else item
                       for item in index["items"]]
    svc.store.values["announcement_flash_result_index"] = index

    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})
    assert response.status_code == 409
    assert "RECOVERY_PARENT_UNVERIFIED" in response.text
    assert svc.jobs.submissions == []


def test_http_date_only_rejects_tampered_intermediate_recovery_result_link():
    case = _saved_r8c_zero_candidate_case()
    svc = case["service"]
    intermediate_id = case["input"]["recovery_lock"]["parent_job_id"]
    intermediate = json.loads(svc.store.files[f"announcement_flash/jobs/{intermediate_id}/input.json"])
    next_id = intermediate["recovery_lock"]["parent_job_id"]
    result_ref = f"announcement_flash/jobs/{next_id}/result.json"
    result = json.loads(svc.store.files[result_ref])
    result["counts"] = dict(result.get("counts", {}), failed=999)
    svc.store.files[result_ref] = update_module._canonical(result) + b"\n"

    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})
    assert response.status_code == 409
    assert "RECOVERY_PARENT_UNVERIFIED" in response.text
    assert svc.jobs.submissions == []


def test_http_date_button_continues_exact_saved_identity_conflict_partial_from_current_parent():
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    case = _saved_r8_identity_conflict_case()
    svc = case["service"]
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})
    assert response.status_code == 202, response.text
    assert len(svc.jobs.submissions) == 1
    child = next(job for job_id, job in svc.jobs.jobs.items() if job_id != case["input"]["job_id"])
    assert child.context.cutoff == case["input"]["cutoff"]
    assert child.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RECOVERY"
    parent = child.context.scope_refs["announcement_recovery_parent"]
    assert parent["job_id"] == case["input"]["job_id"]
    assert parent["root_batch_job_id"] == case["input"]["recovery_lock"]["root_batch_job_id"]
    assert parent["job_id"] != case["input"]["recovery_lock"]["parent_job_id"]
    assert parent["input_sha256"] == update_module._sha(update_module._canonical(case["input"]))
    assert parent["result_sha256"] == case["result_sha"]
    assert parent["capture_product"] == case["capture_ref"]
    assert parent.get("recoverable_system_stop_code") == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"

    capture_store = SimpleNamespace(io=SimpleNamespace(
        read_bytes=lambda ref, **_kwargs: case["capture_raw"] if ref == case["capture_ref"]["artifact_ref"]
        else (_ for _ in ()).throw(FileNotFoundError(ref))))
    update = AnnouncementUpdate(svc)
    next_lock, fresh_gate = update._prepare_recovery_lock(child, parent, capture_store)
    old_lock = case["input"]["recovery_lock"]
    assert next_lock["root_batch_job_id"] == old_lock["root_batch_job_id"]
    assert next_lock["parent_job_id"] == case["input"]["job_id"]
    assert next_lock["cutoff"] == case["input"]["cutoff"]
    assert next_lock["membership_authority_sha256"] == old_lock["membership_authority_sha256"]
    assert next_lock["row_manifest_sha256"] == old_lock["row_manifest_sha256"]
    assert next_lock["eligible_article_ids_sha256"] == old_lock["eligible_article_ids_sha256"]
    assert next_lock["expected_body_sha256"] == old_lock["current_body_sha256"]
    assert fresh_gate["authority_sha256"] == old_lock["membership_authority_sha256"]
    verified = update._verify_recovery_capture(case["capture"], case["capture_ref"], next_lock,
                                               fresh_gate, case["input"]["cutoff"])
    assert verified["capture_product_sha256"] == case["capture_ref"]["sha256"]
    assert verified["current_body_sha256_digest"] == old_lock["current_body_sha256_digest"]
    assert svc.jobs.submissions[0][0].scope_refs["announcement_recovery_parent"]["job_id"] == "85add37723bf4c5ea1445dcb61202899"
    for path, before_sha in case["snapshots"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before_sha


def test_http_date_button_fails_closed_for_unverified_queue_identity_stop():
    case = _saved_r8_identity_conflict_case()
    svc = case["service"]
    progress = dict(case["progress"])
    progress["failure_code"] = "TransportError"
    svc.store.files[f"announcement_flash/jobs/{case['input']['job_id']}/progress.json"] = (
        update_module._canonical(progress) + b"\n")

    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})

    assert response.status_code == 409
    assert "RECOVERY_PARENT_UNVERIFIED" in response.text
    assert len(svc.jobs.submissions) == 0


def _r8c_attach_failed_prequeue_child(case, *, tamper_parent_stop_binding=False):
    from copy import deepcopy
    from types import SimpleNamespace

    svc = case["service"]
    target_date = case["input"]["target_date"]
    parent_job_id = case["input"]["job_id"]
    parent_binding = AnnouncementUpdate(svc)._recovery_parent(target_date)
    assert parent_binding is not None
    parent_binding = deepcopy(parent_binding)
    if tamper_parent_stop_binding:
        parent_binding["failure_progress_sha256"] = "0" * 64
    child_id = "d" * 32
    capture_identity = {
        "recovery_parent_job_id": parent_binding["job_id"],
        "recovery_parent_input_sha256": parent_binding["input_sha256"],
        "recovery_parent_result_sha256": parent_binding["result_sha256"],
        "capture_product_sha256": parent_binding["capture_product"]["sha256"],
        "target_date": target_date, "cutoff": parent_binding["cutoff"],
    }
    recovery_lock = deepcopy(case["input"]["recovery_lock"])
    recovery_lock.update({
        "root_batch_job_id": parent_binding["root_batch_job_id"],
        "parent_job_id": parent_job_id,
        "parent_input_sha256": parent_binding["input_sha256"],
        "parent_result_sha256": parent_binding["result_sha256"],
        "parent_capture_product_sha256": parent_binding["capture_product"]["sha256"],
        "capture_product_sha256": parent_binding["capture_product"]["sha256"],
    })
    child_input = {
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": child_id, "target_date": target_date, "cutoff": parent_binding["cutoff"],
        "capture_product": deepcopy(parent_binding["capture_product"]),
        "membership_gate": deepcopy(case["input"]["membership_gate"]),
        "recovery_lock": recovery_lock,
    }
    svc.store.files[f"announcement_flash/jobs/{child_id}/input.json"] = update_module._canonical(child_input)
    svc.store.files[f"announcement_flash/jobs/{child_id}/progress.json"] = update_module._canonical({
        "step": "FAILED", "failure_code": "RECOVERY_BODY_BINDING_INVALID"})
    child_context = SimpleNamespace(
        target_date=target_date, cutoff=parent_binding["cutoff"],
        scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_RECOVERY",
                    "capture_input_sha256": update_module.digest(capture_identity),
                    "announcement_recovery_parent": parent_binding})
    svc.store.values["announcement_flash_latest"] = {
        "job_id": child_id, "target_date": target_date, "state": "FAILED",
        "result_state": "PARTIAL", "result_sha256": parent_binding["result_sha256"]}
    svc.jobs.jobs[child_id] = SimpleNamespace(
        job_id=child_id, state=JobState.FAILED, context=child_context,
        step="FLASH_SELECTION", failed_steps=["FLASH_SELECTION"],
        failure_code="RECOVERY_BODY_BINDING_INVALID")
    return svc, parent_binding, child_id


def test_http_date_button_composes_failed_prequeue_child_fallback_with_queue_stop_parent():
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    case = _saved_r8_identity_conflict_case()
    svc, prior_parent_binding, _failed_child_id = _r8c_attach_failed_prequeue_child(case)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})

    assert response.status_code == 202, response.text
    assert len(svc.jobs.submissions) == 1
    child = next(job for job_id, job in svc.jobs.jobs.items()
                 if job_id not in {case["input"]["job_id"], "d" * 32})
    assert child.context.cutoff == case["input"]["cutoff"]
    assert child.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RECOVERY"
    parent = child.context.scope_refs["announcement_recovery_parent"]
    assert parent["job_id"] == case["input"]["job_id"]
    assert parent["root_batch_job_id"] == case["input"]["recovery_lock"]["root_batch_job_id"]
    assert parent["input_sha256"] == update_module._sha(update_module._canonical(case["input"]))
    assert parent["result_sha256"] == case["result_sha"]
    assert parent["recoverable_system_stop_code"] == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
    assert parent["failure_progress_sha256"] == prior_parent_binding["failure_progress_sha256"]

    capture_store = SimpleNamespace(io=SimpleNamespace(
        read_bytes=lambda ref, **_kwargs: case["capture_raw"] if ref == case["capture_ref"]["artifact_ref"]
        else (_ for _ in ()).throw(FileNotFoundError(ref))))
    next_lock, fresh_gate = AnnouncementUpdate(svc)._prepare_recovery_lock(child, parent, capture_store)
    assert next_lock["parent_job_id"] == case["input"]["job_id"]
    assert next_lock["root_batch_job_id"] == case["input"]["recovery_lock"]["root_batch_job_id"]
    assert next_lock["cutoff"] == case["input"]["cutoff"]
    assert next_lock["row_manifest_sha256"] == case["input"]["recovery_lock"]["row_manifest_sha256"]
    assert next_lock["eligible_article_ids_sha256"] == case["input"]["recovery_lock"]["eligible_article_ids_sha256"]
    assert fresh_gate["authority_sha256"] == case["input"]["recovery_lock"]["membership_authority_sha256"]
    for path, before_sha in case["snapshots"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before_sha


def test_http_date_button_rejects_failed_child_when_parent_stop_binding_is_invalid():
    case = _saved_r8_identity_conflict_case()
    svc, _parent_binding, _failed_child_id = _r8c_attach_failed_prequeue_child(
        case, tamper_parent_stop_binding=True)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).post(api.PREFIX + "/announcement-flash/update",
                                    json={"target_date": "20261016"})

    assert response.status_code == 409
    assert "RECOVERY_PARENT_UNVERIFIED" in response.text
    assert len(svc.jobs.submissions) == 0
