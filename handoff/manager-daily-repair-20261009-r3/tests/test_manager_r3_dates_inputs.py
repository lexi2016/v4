"""R3 exact-date/input contracts using synthetic sources and the real owners.

Only fixture source documents and clocks are injected. The announcement import,
workspace owner, product/attempt store, and HTTP routes are application code.
These tests neither access live state nor establish Mac/API/UI/natural recovery.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest

import test_manager_announcement_parity_20261008 as announcement_fixture
from test_manager_announcement_parity_20261008 import (
    _FixtureService, _client, _fixture, _import, _snapshot,
)
from v4.manager_research import workspace
from v4.manager_research.workspace_projection import FLAGS, HK


CURRENT = "20261009"
CATCH_UP = "20261008"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"


def _freeze(monkeypatch, actual: datetime) -> None:
    """Keep capture/import, owner execution and subsequent GET times explicit."""
    class RouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return actual.astimezone(tz) if tz else actual.replace(tzinfo=None)

    monkeypatch.setattr(announcement_fixture.api, "datetime", RouterClock)
    monkeypatch.setattr(announcement_fixture.consumer, "_now", lambda: actual.isoformat())
    monkeypatch.setattr(announcement_fixture, "NOW", actual + timedelta(seconds=2))
    monkeypatch.setattr(workspace, "_now", lambda: (actual + timedelta(seconds=1)).isoformat())


@pytest.fixture
def service(tmp_path, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 10, 9, 10, 0, tzinfo=HK))
    owner = _FixtureService(tmp_path / "synthetic-manager-state")
    # No tested path may turn a source read into capture or a second producer.
    monkeypatch.setattr(owner, "refresh_announcements",
        lambda *a, **k: pytest.fail("workspace started announcement collection"))
    monkeypatch.setattr(owner, "refresh_catalyst_observations",
        lambda *a, **k: pytest.fail("workspace started catalyst collection"))
    monkeypatch.setattr(owner, "refresh_us_mapping_research",
        lambda *a, **k: pytest.fail("workspace started daily mapping production"))
    try:
        yield owner
    finally:
        owner.close()


def _source(service, client, *, target=CURRENT, publication="2026-10-08",
            run_id="1" * 32, disposition="SELECTED_EVENT", import_product=True,
            **options):
    target_iso = f"{target[:4]}-{target[4:6]}-{target[6:]}"
    product, registration = _fixture(service, target=target, publication=publication,
        run_id=run_id, listing_at=publication + "T21:00:00+00:00",
        body_at=publication + "T21:01:00+00:00",
        reviewed_at=target_iso + "T00:00:00+00:00", disposition=disposition,
        **options)
    assert registration is not None
    if import_product:
        _import(client, registration)
    return product, registration


def _refresh(client, *, target=CURRENT, publication="20261008"):
    return client.post("/api/v4/manager/research/workspace/refresh",
        params={"date": target, "selection_date": target,
                "announcement_date": publication},
        headers={"Origin": "http://testserver"})


def _read(client, *, target=CURRENT, publication="20261008", view=None):
    params = {"date": target, "selection_date": target,
              "announcement_date": publication}
    if view is not None:
        params["view"] = view
    response = client.get("/api/v4/manager/research/workspace", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _channels(value):
    return {row["channel"]: row for row in value["daily_channels"]["channels"]}


def _stored_content(service):
    # Kernel admission may create a mutex file; it is not a research artifact
    # or an owner attempt and does not establish materialization.
    return {name: sha for name, sha in _snapshot(service.store.root).items()
            if not name.startswith(".locks/")}


def _assert_same_product(saved, read, *, target, publication):
    product = read["plan_product"]
    run = product["run_readback"]
    assert read["target_trade_date"] == target
    assert read["date_bindings"] == {
        "plan_date": target, "selection_date": target,
        "announcement_date": publication,
    }
    assert product["status"] == "CURRENT"
    assert product["consumed"] is True
    assert product["run_id"] == saved["plan_product"]["run_id"] == run["run_id"]
    assert product["sha256"] == saved["plan_product"]["sha256"] == run["artifact_sha256"]
    assert read["input_identity"] == saved["input_identity"] == run["input_identity"]
    assert read["plan_context"] == saved["plan_context"]
    assert product["original_owner"] == run["owner"] == OWNER
    assert run["status"] == "VERIFIED"
    assert run["owner_attempt_run_id"] == product["run_id"]
    assert all(read[key] is flag for key, flag in FLAGS.items())
    assert all(channel["natural_run_verified"] is False
               for channel in read["daily_channels"]["channels"])


def _assert_selected_source(value, product, registration, *, target, publication):
    announcement = _channels(value)["ANNOUNCEMENT"]
    assert announcement["status"] == "READY"
    assert announcement["candidate_count"] == 1
    row, = announcement["rows"]
    assert row["symbol"] == "HK.01234"
    assert row["reason"] == "Synthetic fixture disposition only."
    assert row["target_trade_date"] == target
    assert row["data_date"] == publication
    assert row["run_id"] == registration["evidence_run_id"]
    assert row["product_sha256"] == product["sha256"]
    assert row["source_manifest_sha256"] == product["source_manifest_sha256"]
    assert row["source_refs"]
    consumed, = value["announcement_reviewed_analysis"]["products"]
    assert consumed["status"] == "CONSUMED"
    assert consumed["evidence_run_id"] == row["run_id"]
    assert consumed["product_sha256"] == row["product_sha256"]
    assert consumed["owner_import_receipt_sha256"]


def test_retrospective_1008_dynamic_reads_saved_identity_without_changing_auto_history(service):
    with _client(service) as client:
        product, registration = _source(service, client, target=CATCH_UP,
            publication="2026-10-07")
        posted = _refresh(client, target=CATCH_UP, publication="20261007")
        assert posted.status_code == 200, posted.text
        saved = posted.json()
        assert saved["plan_product"]["execution_context"]["timing"] == "RETROSPECTIVE"
        assert saved["plan_context"]["research_cutoff"] == "2026-10-09T10:00:00+08:00"
        initial = _snapshot(service.store.root)
        dynamic = _read(client, target=CATCH_UP, publication="20261007", view="dynamic")
        _assert_same_product(saved, dynamic, target=CATCH_UP, publication="20261007")
        _assert_selected_source(dynamic, product, registration,
            target=CATCH_UP, publication="20261007")
        historical_auto = _read(client, target=CATCH_UP, publication="20261007")
        assert historical_auto["plan_product"]["consumed"] is False
        assert historical_auto["plan_product"]["run_id"] is None
        assert historical_auto["read_context"]["reason"] == "HISTORY_QUALIFIED_SAVED_PLAN_MISSING"
        assert _snapshot(service.store.root) == initial


def test_retrospective_latest_preserves_1008_qualified_auto_history(service, monkeypatch):
    early = datetime(2026, 10, 8, 9, 27, tzinfo=HK)
    _freeze(monkeypatch, early)
    with _client(service) as client:
        _source(service, client, target=CATCH_UP, publication="2026-10-07")
        posted = _refresh(client, target=CATCH_UP, publication="20261007")
        assert posted.status_code == 200, posted.text
        original = posted.json()
        # The existing low-level scheduled owner establishes normal historical
        # eligibility; this is an actual write, not a resealed success DTO.
        original = service.refresh_workspace_plan(CATCH_UP,
            execution_kind="SCHEDULED_PREOPEN", now=early,
            deadline=datetime(2026, 10, 8, 9, 30, tzinfo=HK))
        path = service.store.root / "workspace_plans" / CATCH_UP / (
            original["plan_product"]["run_id"] + ".json")
        original_bytes = path.read_bytes()
        _freeze(monkeypatch, datetime(2026, 10, 9, 10, 0, tzinfo=HK))
        late = _refresh(client, target=CATCH_UP, publication="20261007")
        assert late.status_code == 200, late.text
        retrospective = late.json()
        assert retrospective["plan_product"]["run_id"] != original["plan_product"]["run_id"]
        initial = _snapshot(service.store.root)
        dynamic = _read(client, target=CATCH_UP, publication="20261007", view="dynamic")
        _assert_same_product(retrospective, dynamic, target=CATCH_UP, publication="20261007")
        historical_auto = _read(client, target=CATCH_UP, publication="20261007")
        assert historical_auto["plan_product"]["status"] == "CURRENT", historical_auto["read_context"]
        assert historical_auto["plan_product"]["consumed"] is True
        assert historical_auto["plan_product"]["run_id"] == original["plan_product"]["run_id"]
        assert historical_auto["plan_product"]["sha256"] == original["plan_product"]["sha256"]
        assert historical_auto["input_identity"] == original["input_identity"]
        assert historical_auto["workspace_plan_attempt"] == original["workspace_plan_attempt"]
        assert historical_auto["plan_context"] == original["plan_context"]
        assert path.read_bytes() == original_bytes
        assert _snapshot(service.store.root) == initial


def test_current_1009_default_auto_reads_same_saved_run_sha_inputs_and_stock_reason(service):
    with _client(service) as client:
        product, registration = _source(service, client)
        posted = _refresh(client)
        assert posted.status_code == 200, posted.text
        saved = posted.json()
        initial = _snapshot(service.store.root)
        read = _read(client)  # Ordinary browser contract: no explicit view.
        _assert_same_product(saved, read, target=CURRENT, publication="20261008")
        _assert_selected_source(read, product, registration,
            target=CURRENT, publication="20261008")
        assert _snapshot(service.store.root) == initial


@pytest.mark.parametrize("source_state", ["absent", "captured_not_imported"])
@pytest.mark.parametrize("target,publication", [(CURRENT, "20261008"), (CATCH_UP, "20261007")])
def test_all_unavailable_inputs_do_not_materialize_a_plan_or_invent_zero(service, source_state, target, publication):
    with _client(service) as client:
        if source_state == "captured_not_imported":
            publication_iso = f"{publication[:4]}-{publication[4:6]}-{publication[6:]}"
            _source(service, client, target=target, publication=publication_iso, import_product=False)
        initial = _stored_content(service)
        response = _refresh(client, target=target, publication=publication)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result.get("status") == "CANNOT_CONFIRM"
        assert result["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
        assert result["failure_reasons"]
        assert result["plan_product"]["consumed"] is False
        assert result["plan_product"]["run_id"] is None
        assert result["plan_product"]["sha256"] is None
        assert result.get("workspace_plan_attempt") is None
        assert service.get_workspace_plan(target) is None
        assert _stored_content(service) == initial
        read = _read(client, target=target, publication=publication, view="dynamic")
        assert read["plan_product"]["run_id"] is None
        assert read["plan_product"]["consumed"] is False
        assert read["read_context"]["candidate_count_known"] is False
        assert all(channel["candidate_count"] is None for channel in _channels(read).values())
        assert read["us_mapping_research"]["daily_run"]["status"] == "NOT_RUN"
        assert read["us_mapping_research"]["daily_run"]["run_id"] is None


def test_new_input_failure_preserves_previous_plan_and_same_run_attempt(service):
    with _client(service) as client:
        _source(service, client)
        posted = _refresh(client)
        assert posted.status_code == 200, posted.text
        original = service.get_workspace_plan(CURRENT)
        assert original is not None
        initial = _stored_content(service)
        # Only the injected source becomes unavailable; immutable owner
        # products, receipts and evidence files remain in the fixture store.
        service.catalogs.clear()
        refused = _refresh(client)
        assert refused.status_code == 200, refused.text
        assert refused.json()["status"] == "CANNOT_CONFIRM"
        assert refused.json()["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
        assert service.get_workspace_plan(CURRENT) == original
        assert _stored_content(service) == initial


@pytest.mark.parametrize("fixture_options,pending", [({"reader_gap": True}, 1), ({"no_decisions": True}, None)])
def test_unassessed_import_does_not_authorize_a_successful_empty_plan(service, fixture_options, pending):
    with _client(service) as client:
        _source(service, client, **fixture_options)
        before = _stored_content(service)
        response = _refresh(client)
        assert response.status_code == 200, response.text
        value = response.json()
        assert value.get("status") == "CANNOT_CONFIRM"
        assert value["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
        announcement = _channels(value)["ANNOUNCEMENT"]
        assert announcement["status"] == "PARTIAL"
        assert announcement["candidate_count"] is None
        assert announcement["pending_count"] == pending
        assert "ANNOUNCEMENT_SELECTION_NOT_ASSESSED" in value["failure_reasons"]
        assert service.get_workspace_plan(CURRENT) is None
        assert _stored_content(service) == before


def test_verified_not_selected_input_saves_traceable_empty_result(service):
    with _client(service) as client:
        product, registration = _source(service, client, disposition="NOT_SELECTED")
        response = _refresh(client)
        assert response.status_code == 200, response.text
        result = response.json()
        saved = service.get_workspace_plan(CURRENT)
        assert saved is not None
        assert saved["run_id"] == result["plan_product"]["run_id"]
        assert saved["sha256"] == result["plan_product"]["sha256"]
        assert saved["input_identity"] == result["input_identity"]
        assert saved["owner"] == OWNER
        announcement = _channels(saved["workspace"])["ANNOUNCEMENT"]
        assert announcement["status"] == "READY_EMPTY"
        assert announcement["candidate_count"] == announcement["pending_count"] == 0
        assert announcement["rows"] == []
        consumed, = saved["workspace"]["announcement_reviewed_analysis"]["products"]
        assert consumed["status"] == "CONSUMED"
        assert consumed["product_sha256"] == product["sha256"]
        assert consumed["evidence_run_id"] == registration["evidence_run_id"]
        assert consumed["not_selected_stock_count"] == 1
        original_analysis = service.get_announcement_analysis(CURRENT, "2026-10-08")
        decisions = original_analysis["analysis"]["stock_selection"]["article_decisions"]
        assert decisions[0]["disposition"] == "NOT_SELECTED"
        assert decisions[0]["reason"] == "Synthetic fixture disposition only."
        _assert_same_product(result, _read(client), target=CURRENT, publication="20261008")


@pytest.mark.parametrize("failure", [RuntimeError, ImportError])
def test_unavailable_us_channel_preserves_verified_announcement_stock_and_evidence(service, failure):
    with _client(service) as client:
        product, registration = _source(service, client)

        def unavailable(_session):
            raise failure("Synthetic independent US source unavailable")

        service._workspace_us_market_reader = SimpleNamespace(read_exact_session=unavailable)
        posted = _refresh(client)
        assert posted.status_code == 200, posted.text
        saved = posted.json()
        read = _read(client)
        _assert_same_product(saved, read, target=CURRENT, publication="20261008")
        _assert_selected_source(read, product, registration,
            target=CURRENT, publication="20261008")
        assert read["us_market_attention"]["status"] == "SOURCE_FAILED"
        assert "US_MARKET_READER_FAILED:" + failure.__name__ in read["us_market_attention"]["gaps"]
        assert read["us_mapping_research"]["daily_run"]["status"] == "NOT_RUN"
        assert read["us_mapping_research"]["daily_run"]["run_id"] is None
        assert _channels(read)["OVERSOLD"]["candidate_count"] is None


@pytest.mark.parametrize("materialize_mapping", [False, True], ids=["capture_only", "valid_empty_mapping"])
def test_verified_us_capture_requires_its_separate_daily_mapping_before_plan_consumption(
        service, tmp_path, monkeypatch, materialize_mapping):
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    from test_manager_us_mapping_research import _synthetic_us_payload
    from v4.manager_research import us_mapping_research
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader

    source_root = tmp_path / "synthetic-us-source"
    ResearchPeripheralStore(source_root).publish(_synthetic_us_payload("20261008", {}))
    service._workspace_us_market_reader = ResearchPeripheralUsMarketReader(source_root)

    # Supply exact temporary source/registry files. The original readers check
    # their schemas, checksums and availability; no successful mapping DTO or
    # input-validation function is mocked.
    reviewed = {"schema_version": "v4.manager_research.us_mapping_reviewed.v1",
        "target_trade_date": us_mapping_research._TARGET_SEED,
        "report": {"sha256": "a" * 64},
        "cards": [{"daily_match_symbols": [symbol], "hk_symbol": "HK.01234",
            "hk_name": "Synthetic relation issuer", "reason": "Synthetic reviewed relation",
            "official_sources": [{"url": "https://fixture.invalid/synthetic-relation"}]}
            for symbol in ("NVDA", "AMD", "LITE", "AVGO")], **FLAGS}
    reviewed["artifact_sha256"] = us_mapping_research.sha256_json(reviewed)
    seed_path = tmp_path / "synthetic-us-reviewed.json"
    seed_raw = (json.dumps(reviewed, sort_keys=True) + "\n").encode()
    seed_path.write_bytes(seed_raw)
    registry = {"schema_version": "v4.manager_research.us_mapping_relation_registry.v1",
        "source_seed_sha256": hashlib.sha256(seed_raw).hexdigest(),
        "source_report_sha256": reviewed["report"]["sha256"],
        "available_at": "2026-10-01T00:00:00+08:00",
        "availability_basis": "V4_RELEASE_PUBLICATION", "release_id": "SYNTHETIC_TEST_ONLY",
        "release_manifest_sha256": "b" * 64, "deployment_receipt_sha256": "c" * 64}
    registry["artifact_sha256"] = us_mapping_research.sha256_json(registry)
    registry_path = tmp_path / "synthetic-us-registry.json"
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n")
    monkeypatch.setattr(us_mapping_research, "REVIEWED_PATH", seed_path)
    monkeypatch.setattr(us_mapping_research, "RELATION_REGISTRY_PATH", registry_path)

    mapping = None
    if materialize_mapping:
        started = datetime(2026, 10, 9, 9, 59, tzinfo=HK)

        class MappingClock(datetime):
            @classmethod
            def now(cls, tz=None):
                finished = started + timedelta(seconds=1)
                return finished.astimezone(tz) if tz else finished.replace(tzinfo=None)

        monkeypatch.setattr(us_mapping_research, "datetime", MappingClock)
        # Invoke the original owner explicitly once. The service fixture's
        # fail-on-call guard still prevents plan/GET from starting it again.
        mapping = ManagerResearchJobService.refresh_us_mapping_research(
            service, CURRENT, now=started, timeout_seconds=2,
            execution_context={"trigger_kind": "MANUAL", "timing": "UNCLASSIFIED",
                "natural_run_verified": False})
        assert mapping["status"] == "VALID_EMPTY", mapping.get("gaps")
        assert mapping["coverage"]["matched_hk_relation_count"] == 0
        assert mapping["us_session_date"] == "20261008"

    source_before = _snapshot(source_root)
    with _client(service) as client:
        posted = _refresh(client)
        assert posted.status_code == 200, posted.text
        value = posted.json()
        assert value["us_market_attention"]["status"] == "READY"
        assert value["us_market_attention"]["source_identity"]["status"] == "VERIFIED"
        daily = value["us_mapping_research"]["daily_run"]
        reference = value["owner_chain"]["us_mapping_daily_plan_reference"]
        if mapping is None:
            assert daily["status"] == "NOT_RUN" and daily["run_id"] is None
            assert reference["status"] != "CONSUMED"
            assert value["status"] == "CANNOT_CONFIRM"
            assert value["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
            assert service.get_workspace_plan(CURRENT) is None
        else:
            assert reference["status"] == "CONSUMED"
            assert reference["run_id"] == daily["run_id"] == mapping["run_id"]
            assert reference["artifact_sha256"] == daily["artifact_sha256"] == mapping["artifact_sha256"]
            assert daily["input_identity"] == mapping["input_identity"]
            assert daily["source_identity"] == mapping["source_identity"]
            _assert_same_product(value, _read(client), target=CURRENT, publication="20261008")
        # An assessed US empty result does not invent zero counts for the
        # independent, still-unavailable announcement/HK/screen channels.
        assert all(channel["candidate_count"] is None for channel in _channels(value).values())
        assert _snapshot(source_root) == source_before
