"""Hermetic producer -> owner receipt -> mapping and scheduling canaries."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import pytest

from infrastructure.research_peripheral_store import ResearchPeripheralStore, _validate_market_snapshot
from ops.materialize_research_peripherals import build_external_finance_payload
from ops.us_market_digest import build_us_market_snapshot, resolve_capture_for_shanghai_slot
from ops.run_us_market_slot import _request_for_slot
from v4.manager_workbench.binding import CalendarAdapter
from v4.manager_workbench.contracts import Counts, JobState, Phase, seal_snapshot
from v4.manager_workbench.inputs import source_bindings
from v4.manager_workbench.inputs.us_universe import build_us_universe_contract
from v4.manager_workbench.engines.us_mapping_consumption import build_catalog_candidates, project_catalog_relation
from v4.manager_workbench.scheduler import _us_close_handoff

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/handoffs/us_mapping_auto_close_20261020/quote_scope.json"
CAPTURED = "2026-10-19T20:15:04Z"
CUTOFF = "2026-10-20T04:16:00+08:00"


def quotes():
    symbols = json.loads(CONFIG.read_text())["symbols"]
    data = {"v_us" + s: {"symbol": s, "last": 101.0, "previous_close": 100.0,
                "session_date": "20261019", "session_time": "16:00:02"} for s in symbols}
    for s, last in [("WMT", 100.8), ("KO", 102.0), ("PG", 101.4)]:
        data["v_us" + s]["last"] = last
    return data


def snapshot(monkeypatch, data=None, *, captured=CAPTURED):
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    monkeypatch.delenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", raising=False)
    monkeypatch.delenv("V35_APP_ROOT", raising=False)
    return build_us_market_snapshot("20261019", capture_phase="POST_CLOSE", captured_at=captured,
                                    universe_contract=build_us_universe_contract(),
                                    fetch_quotes=lambda *_: data if data is not None else quotes())


def test_one_provider_call_main_48_semantics_unchanged_and_no_preopen_fetch(monkeypatch):
    data = quotes()
    calls = []
    def fetch(url, _timeout):
        calls.append(url)
        return data
    monkeypatch.delenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", raising=False)
    contract = build_us_universe_contract()
    baseline = build_us_market_snapshot("20261019", captured_at=CAPTURED,
                                        universe_contract=contract, fetch_quotes=fetch)
    calls.clear()
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    new = build_us_market_snapshot("20261019", captured_at=CAPTURED,
                                   universe_contract=contract, fetch_quotes=fetch)
    assert len(calls) == 1
    assert len(calls[0].split("q=")[1].split(",")) == 547
    assert new["requested_symbol_count"] == new["available_symbol_count"] == 48
    assert new["scheduled_quote_scope"]["available_symbol_count"] == 547
    # Request URL honestly records the expanded single request; all original
    # quote/row/status/48-symbol contract fields must remain identical.
    assert {k: v for k, v in new.items() if k not in {"quote_url", "scheduled_quote_scope"}} == {
        k: v for k, v in baseline.items() if k != "quote_url"}
    _validate_market_snapshot(new)
    calls.clear()
    preopen = build_us_market_snapshot("20261019", capture_phase="PRE_OPEN",
                                       captured_at="2026-10-19T13:00:01Z", universe_contract=contract,
                                       fetch_quotes=fetch)
    assert calls == []
    assert preopen["available_symbol_count"] == 0
    assert "scheduled_quote_scope" not in preopen


def test_invalid_extra_source_does_not_change_main_and_keeps_valid_peers(monkeypatch):
    data = quotes()
    data["v_usWMT"]["symbol"] = "KO"
    data["v_usKO"]["last"] = -1
    out = snapshot(monkeypatch, data)
    assert out["status"] == "READY"
    scope = out["scheduled_quote_scope"]
    assert scope["state"] == "PARTIAL"
    assert "WMT" not in {q["symbol"] for q in scope["quotes"]}
    assert "KO" not in {q["symbol"] for q in scope["quotes"]}
    assert "PG" in {q["symbol"] for q in scope["quotes"]}
    assert scope["quote_failures"]["WMT"] == "QUOTE_SYMBOL_MISMATCH"


def _write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("late", [False, True])
def test_actual_source_binding_consumes_scheduled_owner_and_keeps_dated_candidates(tmp_path, monkeypatch, late):
    from ops.us_market_digest import build_capture_metadata, build_us_market_phase_payload
    captured = "2026-10-19T21:15:04Z" if late else CAPTURED
    cutoff = "2026-10-20T05:16:00+08:00" if late else CUTOFF
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    universe_config = tmp_path / "owner-universe.json"
    universe_config.write_text(json.dumps({"source_bindings": {}}))
    monkeypatch.setenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", str(universe_config))
    payload = build_us_market_phase_payload("20261020", capture_phase="POST_CLOSE",
        us_session_date="20261019", fetched_at=captured,
        capture_id="synthetic-automatic-close", run_id="synthetic-automatic-close",
        fetch_rss=lambda *_args, **_kwargs: b"<rss><channel></channel></rss>",
        fetch_quotes=lambda *_args, **_kwargs: quotes(), allow_late_post_close=late, now=captured)
    capture = payload["us_session_captures"][0]
    quote_root = tmp_path / "quotes"
    store = ResearchPeripheralStore(quote_root)
    # The real dedicated owner uses the Shanghai artifact date: the same US
    # session has PRE_OPEN on HK19 and POST_CLOSE on HK20. Only the close is
    # a directional input; their coexistence must not fail uniqueness.
    preopen = build_external_finance_payload("20261019", fetched_at="2026-10-19T13:00:01Z", subscriptions=())
    preopen_market = build_us_market_snapshot("20261019", capture_phase="PRE_OPEN",
        captured_at="2026-10-19T13:00:01Z", universe_contract=build_us_universe_contract(),
        fetch_quotes=lambda *_: (_ for _ in ()).throw(AssertionError("PRE_OPEN fetched quotes")))
    preopen.update(market_snapshot=preopen_market, market_snapshot_status="CANNOT_CONFIRM", status="CANNOT_CONFIRM")
    preopen["us_session_captures"] = [build_capture_metadata("20261019", "PRE_OPEN",
        captured_at="2026-10-19T13:00:01Z", capture_id="synthetic-preopen", run_id="synthetic-preopen")]
    store.publish(preopen)
    store.publish(payload)
    relations = tmp_path / "relations"
    evidence = {"schema_version": "frozen", "relations": [], "symbol_assessments": []}
    evidence["artifact_sha256"] = source_bindings.owner_digest(evidence)
    evidence_sha = _write(relations, "evidence.json", evidence)
    review = {"status": "PASS", "evidence_file_sha256": evidence_sha,
              "declared_artifact_sha256": evidence["artifact_sha256"],
              "recomputed_artifact_sha256": evidence["artifact_sha256"],
              "reviewer_identity": "synthetic-reviewer", "reviewed_at": "2026-10-13T07:00:00Z",
              "reviewed_pairs": [], "reviewed_symbol_assessments": [], "safety": {"production_allowed": False}}
    _write(relations, "review.json", review)
    config = SimpleNamespace(us_root=quote_root, relation_root=relations,
                             relation_evidence_relative="evidence.json", relation_review_relative="review.json",
                             source_bindings={})
    context = SimpleNamespace(source_sessions={"us": "20261019"}, cutoff=cutoff, target_date="20261020")
    monkeypatch.setattr(source_bindings, "priority_review", lambda *_: [])
    monkeypatch.setattr(source_bindings, "reviewed_seed", lambda *_: ([], []))
    monkeypatch.setattr(source_bindings, "us_factor_exposure", lambda *_: (None, [], None))
    monkeypatch.setattr(source_bindings, "hk_industry_classification", lambda *_: {"checked_files": []})
    monkeypatch.setattr(source_bindings, "_full_mapping_overlay", lambda: {"state": "READY", "relations": []})
    def forbid_manual(*_):
        raise AssertionError("natural owner must not fall back to historical manual data")
    monkeypatch.setattr(source_bindings, "_manual_quote_scope_binding", forbid_manual)
    pin = source_bindings.us_mapping(config, context)
    bound = pin["manual_quote_scope"]
    assert len(pin["configured_symbols"]) == 48
    assert bound["owner"].endswith(".scheduled_quote_scope")
    assert bound["us_session_date"] == "20261019"
    assert bound["late"] is late
    assert all(value == capture[key] for key, value in bound["capture_metadata"].items())
    fixtures = runpy.run_path(str(ROOT / "tests/manager_workbench/engines/test_us_mapping_consumption.py"))
    rows = []
    for rid, symbol, code in [("R924", "WMT", "06808"), ("R955", "KO", "09633"), ("R942", "PG", "06993")]:
        row = fixtures["_row"](rid, symbol, code=code, current="DATED_SCOPE_ONLY")
        rows.append(project_catalog_relation(row, manual_binding=bound, expected_session="20261019", cutoff=cutoff))
    candidates = build_catalog_candidates(rows)
    assert [row["hk_code"] for row in candidates] == ["09633", "06993", "06808"]
    assert all(row["qualification"] == "DATED_WEAK_PEER" for row in candidates)
    assert all(row["owner"].endswith(".scheduled_quote_scope") for row in rows)


def test_new_postclose_input_runs_despite_same_target_old_plans_and_deduplicates(tmp_path):
    fixtures = runpy.run_path(str(ROOT / "tests/manager_workbench/test_us_close_handoff_scheduler.py"))
    Service = fixtures["Service"]
    service = Service(tmp_path, fixtures["_pin"](
        capture_session_date="20261019", capture_cutoff=CAPTURED,
        quote_relative="research/peripherals/20261020/external_finance.json",
        owner_receipt_relative="receipts/research/peripherals/20261020/external_finance.json"), fixtures["_succeed"])
    service.adapters._us_session = lambda _: "20261019"
    old_context = service._make_context
    def make_context(*args, **kwargs):
        value = old_context(*args, **kwargs)
        value.source_sessions["us"] = "20261019"
        return value
    service._make_context = make_context
    try:
        # Existing old-session MANUAL and NEXT_DAY plans are preserved.
        for phase, run in [(Phase.MANUAL, "1" * 32), (Phase.NEXT_DAY, "2" * 32)]:
            context = make_context("20261020", phase, datetime.fromisoformat(CUTOFF), {}, [])
            context.source_sessions["us"] = "20261016"
            plan = seal_snapshot({"context": context.model_dump(mode="json"), "run_id": run,
                                  "input_sha256": "e" * 64, "generated_at": "2026-10-19T18:00:00+08:00",
                                  "available_at": "2026-10-19T18:00:00+08:00", "lanes": [], "stocks": [],
                                  "counts": Counts().model_dump(mode="json"), "gaps": []})
            service.store.commit_plan(plan)
        calendar = CalendarAdapter()
        local = datetime.fromisoformat(CUTOFF)
        result = _us_close_handoff(service, calendar=calendar, local=local)
        assert len(result) == 1 and result[0]["us_session_date"] == "20261019"
        assert result[0]["target_date"] == "20261020"
        job = fixtures["_wait_for_state"](service, result[0]["job_id"], JobState.SUCCEEDED)
        fixtures["_wait_for_scope_release"](service, job.job_id)
        assert job.context.trigger == "SCHEDULED" and job.context.phase == Phase.NEXT_DAY
        assert _us_close_handoff(service, calendar=calendar,
                                 local=datetime.fromisoformat("2026-10-20T05:16:00+08:00")) == []
        assert len(service.submissions) == 1
        assert len(service.store.list_plans("20261020")) == 2
    finally:
        service.stop()


def test_existing_official_calendar_slot_and_same_session_retry_rules(tmp_path):
    assert resolve_capture_for_shanghai_slot("20261020", "0415") == {
        "capture_phase": "POST_CLOSE", "us_session_date": "20261019"}
    assert _request_for_slot(business_date="20261020", slot="0415").target_date == "20261020"
    old = runpy.run_path(str(ROOT / "tests/manager_workbench/test_us_close_handoff_scheduler.py"))
    attempts = []
    def worker(job):
        attempts.append(job.job_id)
        if len(attempts) == 1:
            job.retryable = True
            service.store.save_job(job)
            return job.run_id, JobState.PARTIAL
        return job.run_id, JobState.SUCCEEDED
    service = old["Service"](tmp_path, old["_pin"](
        capture_session_date="20261019", capture_cutoff=CAPTURED,
        quote_relative="research/peripherals/20261020/external_finance.json",
        owner_receipt_relative="receipts/research/peripherals/20261020/external_finance.json"), worker)
    service.adapters._us_session = lambda _: "20261019"
    original = service._make_context
    def make_context(*args, **kwargs):
        result = original(*args, **kwargs)
        result.source_sessions["us"] = "20261019"
        return result
    service._make_context = make_context
    try:
        calendar = CalendarAdapter()
        first = _us_close_handoff(service, calendar=calendar, local=datetime.fromisoformat(CUTOFF))
        old["_wait_for_state"](service, first[0]["job_id"], JobState.PARTIAL)
        old["_wait_for_scope_release"](service, first[0]["job_id"])
        retried = _us_close_handoff(service, calendar=calendar,
                                    local=datetime.fromisoformat("2026-10-20T05:16:00+08:00"))
        assert retried[0]["state"] == "RETRY_SUBMITTED"
        job = old["_wait_for_state"](service, retried[0]["job_id"], JobState.SUCCEEDED)
        old["_wait_for_scope_release"](service, job.job_id)
        assert _us_close_handoff(service, calendar=calendar,
                                 local=datetime.fromisoformat("2026-10-20T05:17:00+08:00")) == []
        assert len(attempts) == 2
    finally:
        service.stop()
