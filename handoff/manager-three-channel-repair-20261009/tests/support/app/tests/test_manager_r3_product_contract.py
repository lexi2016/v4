"""R3 synthetic contracts; original owners, isolated state, no live services.

These fixtures prove date/readback and source projection contracts only. They
do not establish actual 10/8 or 10/9 products, deployment or natural execution.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from test_manager_daily_channels_20261008 import project, target_scope, view
import test_manager_announcement_parity_20261008 as announcement_fixture
from v4.manager_research import workspace, us_mapping_research
from v4.manager_research.workspace_projection import FLAGS, HK


WORKSPACE_URL = "/api/v4/manager/research/workspace"


def _freeze(monkeypatch, at):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)

    monkeypatch.setattr(announcement_fixture.api, "datetime", Clock)
    monkeypatch.setattr(us_mapping_research, "datetime", Clock)
    monkeypatch.setattr(announcement_fixture, "NOW", at + timedelta(seconds=3))
    monkeypatch.setattr(announcement_fixture.consumer, "_now", lambda: at.isoformat())
    monkeypatch.setattr(workspace, "_now", lambda: (at + timedelta(seconds=2)).isoformat())


@pytest.fixture
def service(tmp_path, monkeypatch):
    for key in ("V4_MANAGER_UNIVERSE_ROOT", "V4_MANAGER_UNIVERSE_OWNER_ROOT",
                "V4_MANAGER_UNIVERSE_OWNER_SHA256", "V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT",
                "V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT", "V4_MANAGER_VIBE_BINDING"):
        monkeypatch.delenv(key, raising=False)
    owner = announcement_fixture._FixtureService(tmp_path / "manager-state")
    try:
        yield owner
    finally:
        owner.close()


def _bindings(date):
    publication = "20261007" if date == "20261008" else "20261008"
    return {"date": date, "selection_date": date, "announcement_date": publication}


def _import_research(service, client, date, *, disposition="SELECTED_EVENT"):
    publication = _bindings(date)["announcement_date"]
    publication_iso = datetime.strptime(publication, "%Y%m%d").date().isoformat()
    target_iso = datetime.strptime(date, "%Y%m%d").date().isoformat()
    product, registered = announcement_fixture._fixture(
        service, target=date, publication=publication_iso,
        run_id=("1" if date == "20261008" else "2") * 32,
        listing_at=publication_iso + "T21:00:00+00:00",
        body_at=publication_iso + "T21:01:00+00:00",
        reviewed_at=target_iso + "T00:00:00+00:00", disposition=disposition,
    )
    imported = announcement_fixture._import(client, registered)
    assert imported["consumption_validation"]["validation_status"] == "VERIFIED"
    return product, registered


def _post_plan(client, date):
    response = client.post(WORKSPACE_URL + "/refresh", params=_bindings(date),
                           headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["plan_product"]["status"] == "CURRENT"
    assert result["plan_product"]["consumed"] is True
    return result


def _same_saved_product(value, saved):
    product = value["plan_product"]
    assert value["target_trade_date"] == saved["target_trade_date"]
    assert product["status"] == "CURRENT" and product["consumed"] is True
    assert product["run_id"] == saved["run_id"]
    assert product["sha256"] == saved["sha256"]
    assert value["input_identity"] == saved["input_identity"]
    assert value["date_bindings"] == saved["workspace"]["date_bindings"]
    assert value["plan_context"] == saved["workspace"]["plan_context"]
    assert product["original_owner"] == saved["owner"]
    assert value["workspace_plan_attempt"]["run_id"] == saved["run_id"]
    assert value["workspace_plan_attempt"]["input_identity"] == saved["input_identity"]
    if value["read_context"]["mode"] != "HISTORICAL_AS_OF":
        readback = product["run_readback"]
        assert readback["status"] == "VERIFIED"
        assert readback["run_id"] == readback["owner_attempt_run_id"] == saved["run_id"]
        assert readback["artifact_sha256"] == saved["sha256"]
        assert readback["input_identity"] == saved["input_identity"]
    for result in (value, saved, value["workspace_plan_attempt"], *value["daily_channels"]["channels"]):
        assert all(result[key] is expected for key, expected in FLAGS.items())
    assert all(row["natural_run_verified"] is False for row in value["daily_channels"]["channels"])


def _no_producers(monkeypatch, service):
    def forbidden(*_args, **_kwargs):
        pytest.fail("GET must not invoke any mutating research owner")

    for name in ("refresh_workspace_plan", "refresh_us_mapping_research", "refresh_announcements"):
        monkeypatch.setattr(service, name, forbidden)


def _read(client, date, *, view=None):
    params = _bindings(date)
    if view is not None:
        params["view"] = view
    response = client.get(WORKSPACE_URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("prior_history", [False, True])
def test_1008_retrospective_dynamic_preserves_ordinary_auto_history(service, monkeypatch, prior_history):
    """Making auto consume the retrospective latest run must fail this test."""
    _freeze(monkeypatch, datetime(2026, 10, 8, 8, 30, tzinfo=HK))
    with announcement_fixture._client(service) as client:
        _import_research(service, client, "20261008")
        early = None
        if prior_history:
            early_at = datetime(2026, 10, 8, 9, 27, tzinfo=HK)
            _freeze(monkeypatch, early_at)
            service.refresh_workspace_plan("20261008", execution_kind="SCHEDULED_PREOPEN",
                now=early_at, deadline=datetime(2026, 10, 8, 9, 30, tzinfo=HK))
            early = deepcopy(service.get_workspace_plan("20261008"))

        actual = datetime(2026, 10, 9, 10, 0, tzinfo=HK)
        _freeze(monkeypatch, actual)
        posted = _post_plan(client, "20261008")
        saved = service.get_workspace_plan("20261008")
        assert saved["run_id"] == posted["plan_product"]["run_id"]
        assert saved["execution_context"]["timing"] == "RETROSPECTIVE"
        assert saved["execution_context"]["research_cutoff_policy"] == \
            "ACTUAL_OWNER_EXECUTION_CUTOFF_RETROSPECTIVE"
        assert datetime.fromisoformat(saved["generated_at"]) >= actual
        assert saved["workspace"]["plan_context"]["research_cutoff"] == actual.isoformat()
        before = announcement_fixture._snapshot(service.store.root)
        _no_producers(monkeypatch, service)

        dynamic = _read(client, "20261008", view="dynamic")
        _same_saved_product(dynamic, saved)
        historical = _read(client, "20261008")
        assert historical["read_context"]["mode"] == "HISTORICAL_AS_OF"
        assert historical["plan_product"]["run_id"] != saved["run_id"]
        if early is not None:
            _same_saved_product(historical, early)
            assert historical["workspace_plan_attempt"]["execution_kind"] == "SCHEDULED_PREOPEN"
        else:
            assert historical["plan_product"]["status"] == "NOT_MATERIALIZED"
            assert historical["plan_product"]["consumed"] is False
            assert historical["plan_product"]["run_id"] is None
            assert historical["read_context"]["candidate_count_known"] is False
            assert historical["read_context"]["reason"] == "HISTORY_QUALIFIED_SAVED_PLAN_MISSING"
        assert announcement_fixture._snapshot(service.store.root) == before


@pytest.mark.parametrize("date", ["20261008", "20261009"])
def test_missing_legal_inputs_remain_unknown_without_other_date_fallback(service, monkeypatch, date):
    """An existing other-day plan cannot fill missing exact-date input/result."""
    _freeze(monkeypatch, datetime(2026, 10, 9, 10, 0, tzinfo=HK))
    other_date = "20261009" if date == "20261008" else "20261008"
    with announcement_fixture._client(service) as client:
        _import_research(service, client, other_date)
        other_plan = _post_plan(client, other_date)

        def failed_us_reader(*_args, **_kwargs):
            raise RuntimeError("synthetic isolated US read failure")

        monkeypatch.setattr(us_mapping_research, "read_workspace_mapping", failed_us_reader)
        before = announcement_fixture._snapshot(service.store.root)
        _no_producers(monkeypatch, service)
        value = _read(client, date, view="dynamic" if date == "20261008" else None)
        product = value["plan_product"]
        assert product["status"] == "NOT_MATERIALIZED" and product["consumed"] is False
        assert product["run_id"] is None and product["sha256"] is None
        assert product["run_id"] != other_plan["plan_product"]["run_id"]
        assert value["target_trade_date"] == date
        assert value["stocks"] == []
        assert value["read_context"]["candidate_count_known"] is False
        channels = value["daily_channels"]["channels"]
        assert all(row["status"] == "CANNOT_CONFIRM" for row in channels)
        assert all(row["candidate_count"] is None and row["rows"] == [] and row["gaps"]
                   for row in channels)
        daily = value["us_mapping_research"]["daily_run"]
        assert daily["status"] == "CANNOT_CONFIRM" and daily["target_trade_date"] == date
        assert daily["gaps"] == ["US_MAPPING_READER_UNAVAILABLE:RuntimeError"]
        assert daily["run_id"] is None and daily["artifact_sha256"] is None
        assert daily["source_identity"] is None and daily["matches"] == []
        assert daily["coverage"]["matched_us_symbol_count"] is None
        assert daily["coverage"]["matched_hk_relation_count"] is None
        assert value["market_screen"]["status"] == "CANNOT_CONFIRM"
        assert "SCREEN_AUTHORITY_ROOT_NOT_BOUND" in value["market_screen"]["gaps"]
        assert "HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND" in channels[1]["gaps"]
        announcement = service.get_announcement_analysis(date,
            datetime.strptime(_bindings(date)["announcement_date"], "%Y%m%d").date().isoformat())
        assert announcement["analysis"]["status"] == "NOT_IMPORTED"
        assert announcement_fixture._snapshot(service.store.root) == before


def test_complete_us_source_stays_not_run_until_owner_saves_traceable_valid_empty(
        service, monkeypatch, tmp_path):
    """Capture readiness and a persisted valid-empty daily mapping are distinct."""
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    from manager_daily_ui_owner_fixture import _synthetic_us_payload
    from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader

    source_root = tmp_path / "synthetic-us-source"
    ResearchPeripheralStore(source_root).publish(_synthetic_us_payload("20261008", {}))
    service._workspace_us_market_reader = ResearchPeripheralUsMarketReader(source_root)
    reviewed = {"schema_version": "TEST_FIXTURE", "artifact_sha256": "d" * 64,
        "cards": [{"daily_match_symbols": ["LITE"], "hk_symbol": "HK.06166",
            "hk_name": "Synthetic issuer", "research_priority": "PRIORITY",
            "relationship_type": "PRODUCT_PEER", "reason": "Synthetic reviewed relation",
            "maturity": "TEST_FIXTURE", "limitations": ["synthetic fixture only"],
            "official_sources": []}]}
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(us_mapping_research, "_relation_available_at",
        lambda _reviewed: (datetime(2026, 10, 1, 0, 0, tzinfo=HK), None))
    _freeze(monkeypatch, datetime(2026, 10, 9, 9, 59, tzinfo=HK))
    with announcement_fixture._client(service) as client:
        before = announcement_fixture._snapshot(tmp_path)
        with monkeypatch.context() as read_guard:
            _no_producers(read_guard, service)
            untouched = _read(client, "20261009")
        source = untouched["us_market_attention"]
        assert source["status"] == "READY"
        assert source["source_identity"]["status"] == "VERIFIED"
        assert source["raw_individual_up"] == []
        daily = untouched["us_mapping_research"]["daily_run"]
        assert daily["status"] == "NOT_RUN" and daily["run_id"] is None
        assert daily["coverage"]["matched_hk_relation_count"] is None
        assert untouched["plan_product"]["status"] == "NOT_MATERIALIZED"
        assert announcement_fixture._snapshot(tmp_path) == before

        empty = service.refresh_us_mapping_research("20261009",
            now=datetime(2026, 10, 9, 9, 59, tzinfo=HK), timeout_seconds=2,
            execution_context={"trigger_kind": "MANUAL", "timing": "UNCLASSIFIED",
                               "natural_run_verified": False})
        assert empty["status"] == "VALID_EMPTY" and empty["matches"] == []
        assert empty["coverage"]["configured_us_universe_count"] == 33
        assert empty["coverage"]["available_us_universe_count"] == 33
        assert empty["coverage"]["matched_us_symbol_count"] == 0
        assert empty["coverage"]["matched_hk_relation_count"] == 0
        assert empty["gaps"] == [] and empty["us_session_date"] == "20261008"
        assert empty["source_identity"] == source["source_identity"]
        assert empty["research_cutoff"] == "2026-10-09T09:59:00+08:00"
        assert len(empty["run_id"]) == 32 and len(empty["artifact_sha256"]) == 64
        _freeze(monkeypatch, datetime(2026, 10, 9, 10, 0, tzinfo=HK))
        _post_plan(client, "20261009")
        saved = service.get_workspace_plan("20261009")
        before = announcement_fixture._snapshot(tmp_path)
        _no_producers(monkeypatch, service)
        value = _read(client, "20261009")
        _same_saved_product(value, saved)
        daily = value["us_mapping_research"]["daily_run"]
        for key in ("run_id", "artifact_sha256", "input_identity", "source_identity",
                    "research_cutoff", "us_session_date", "coverage", "matches"):
            assert daily[key] == empty[key]
        assert daily["status"] == "VALID_EMPTY"
        assert daily["run_readback"]["status"] == "VERIFIED"
        assert daily["run_readback"]["owner"] == "ManagerResearchJobService.refresh_us_mapping_research"
        reference = value["owner_chain"]["us_mapping_daily_plan_reference"]
        assert reference["status"] == "CONSUMED"
        assert reference["run_id"] == empty["run_id"]
        assert reference["artifact_sha256"] == empty["artifact_sha256"]
        assert announcement_fixture._snapshot(tmp_path) == before


@pytest.mark.parametrize("disposition", ["SELECTED_EVENT", "NOT_SELECTED"])
def test_1009_saved_plan_default_auto_reads_same_identity_and_legal_channel_result(
        service, monkeypatch, disposition):
    """Complete original announcement evaluation may select one or valid zero."""
    _freeze(monkeypatch, datetime(2026, 10, 9, 10, 0, tzinfo=HK))
    with announcement_fixture._client(service) as client:
        analysis, registered = _import_research(service, client, "20261009", disposition=disposition)
        posted = _post_plan(client, "20261009")
        saved = service.get_workspace_plan("20261009")
        assert saved["run_id"] == posted["plan_product"]["run_id"]
        before = announcement_fixture._snapshot(service.store.root)
        _no_producers(monkeypatch, service)
        value = _read(client, "20261009")
        _same_saved_product(value, saved)
        channel = value["daily_channels"]["channels"][0]
        assert channel["run_id"] == registered["evidence_run_id"]
        assert channel["product_sha256"] == analysis["sha256"]
        assert channel["input_identity"]
        assert channel["pending_count"] == 0
        check = next(item for item in channel["product_checks"] if item["status"] == "CONSUMED")
        assert check["source_manifest_sha256"] == analysis["source_manifest_sha256"]
        assert check["target_trade_date"] == "20261009"
        assert check["publication_date"] == "2026-10-08"
        if disposition == "SELECTED_EVENT":
            assert channel["status"] == "READY" and channel["candidate_count"] == 1
            row = channel["rows"][0]
            assert row["symbol"] == "HK.01234"
            assert row["reason"] == "Synthetic fixture disposition only."
            assert row["data_date"] == "20261008" and row["target_trade_date"] == "20261009"
            assert row["source_manifest_sha256"] == analysis["source_manifest_sha256"]
            assert row["run_id"] == registered["evidence_run_id"]
            assert row["product_sha256"] == analysis["sha256"]
            assert row["source_refs"]
        else:
            assert channel["status"] == "READY_EMPTY"
            assert channel["candidate_count"] == 0 and channel["rows"] == []
            # The full source was evaluated, and its explicit rejection reason
            # remains recoverable through the exact persisted source product.
            source_read = service.get_announcement_analysis("20261009", "2026-10-08")
            selection = source_read["analysis"]["stock_selection"]
            assert selection["not_selected_stock_count"] == 1
            assert selection["article_decisions"][0]["reason"] == "Synthetic fixture disposition only."
        # A verified announcement result never promotes independent gaps to
        # successful zeros or requires a fabricated full-workspace success.
        assert value["workspace_plan_attempt"]["state"] == "PARTIAL"
        for other in value["daily_channels"]["channels"][1:]:
            assert other["status"] == "CANNOT_CONFIRM"
            assert other["candidate_count"] is None and other["gaps"]
        assert announcement_fixture._snapshot(service.store.root) == before


@pytest.mark.parametrize("channel", ["OVERSOLD", "HK_CONNECT"])
def test_original_owner_source_pointers_survive_daily_projection(channel):
    """Losing native payload/manifest keys or one-level card refs must fail."""
    source = view()
    body = "SYNTHETIC_SOURCE_BODY_" * 10000
    native_ref = {
        "owner": "SYNTHETIC_VERIFIED_ORIGINAL_OWNER",
        "source_id": "synthetic-source",
        "source_date": "20261007",
        "payload_path": "synthetic/panel.parquet",
        "payload_sha256": "7" * 64,
        "manifest_path": "synthetic/manifest.json",
        "manifest_sha256": "8" * 64,
        "body": body,
        # Only the original card's immediate source pointers are projected.
        "source_refs": [{"payload_sha256": "9" * 64, "body": body}],
    }
    if channel == "OVERSOLD":
        source["market_screen"].update(
            status="READY", input_identity="6" * 64, gaps=[],
            strict=[{"code": "HK.00001", "reason_for_group": "Original two verified gates",
                     "source_refs": [native_ref]}],
        )
    else:
        source["selection_diagnostics"]["membership"] = target_scope()
        source["stocks"] = [{
            "symbol": "HK.00001", "why_watch": ["Original verified material reason"],
            "connect_eligibility": "VERIFIED_TARGET_UNIVERSE",
            "evidence": [{"card_id": "original-card", "body": body,
                          "source_refs": [native_ref]}],
        }]
        source["focus_symbols"] = ["HK.00001"]
    before = deepcopy(source)
    result = next(row for row in project(source)["channels"] if row["channel"] == channel)
    refs = result["rows"][0]["source_refs"]
    kept = next((ref for ref in refs if ref.get("payload_sha256") == "7" * 64), None)
    assert kept is not None, refs
    for key in ("owner", "source_id", "source_date", "payload_path", "payload_sha256",
                "manifest_path", "manifest_sha256"):
        assert kept[key] == native_ref[key]
    if channel == "HK_CONNECT":
        assert kept["card_id"] == "original-card"
        assert not any(ref.get("payload_sha256") == "9" * 64 for ref in refs)
    assert body not in json.dumps(result)
    assert all(not isinstance(item, (dict, list)) for ref in refs for item in ref.values())
    assert source == before
