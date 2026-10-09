"""Independent API/owner contract checks for the continuation candidate.

All writes are confined to pytest temporary directories. Market payloads are
explicit synthetic fixtures; this module does not contact a live source or
claim deployment, natural scheduling, or production acceptance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


candidate_root = os.environ.get("V4_TEST_SOURCE_ROOT")
if not candidate_root:
    raise RuntimeError("V4_TEST_SOURCE_ROOT must name the frozen candidate source root")
CANDIDATE = Path(candidate_root)
if not CANDIDATE.is_dir() or not (CANDIDATE / "AGENTS.md").is_file():
    raise RuntimeError("V4_TEST_SOURCE_ROOT does not name the expected V4 candidate source root")
sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, str(CANDIDATE / "tests"))

import test_manager_announcement_parity_20261008 as api_fixture
from apps.api.v35_api import manager_research_router as api
from contracts.us_equity_calendar import latest_completed_session
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from v4.manager_research import us_mapping_research, workspace as workspace_owner
from v4.manager_research.announcement_analysis import previous_hk_session
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import digest


HK = ZoneInfo("Asia/Hong_Kong")
TARGET = "20261008"
FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _set_clock(monkeypatch, *, post_at: datetime, generated_at: datetime):
    """Drive a reproducible POST then a later GET through the real HTTP route."""
    clock = {"now": post_at}

    class FrozenRouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock["now"]
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(api, "datetime", FrozenRouterClock)
    monkeypatch.setattr(api_fixture, "NOW", post_at)
    monkeypatch.setattr(workspace_owner, "_now", lambda: generated_at.astimezone(timezone.utc).isoformat())
    return clock


def _set_module_clock(monkeypatch, module, initial: datetime):
    """Inject a coherent owner clock for synthetic multi-owner event order."""
    state = {"now": initial}

    class FrozenOwnerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = state["now"]
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", FrozenOwnerClock)
    return state


def _service(tmp_path, *, reader=None):
    service = api_fixture._FixtureService(tmp_path / "manager-state")
    if reader is not None:
        service._workspace_us_market_reader = reader
    return service


def _post(client, date=TARGET, **params):
    response = client.post(
        "/api/v4/manager/research/workspace/refresh",
        params={"date": date, **params},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get(client, date=TARGET, **params):
    response = client.get(
        "/api/v4/manager/research/workspace",
        params={"date": date, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_omitted_view_post_then_get_reuses_same_day_sealed_context_and_records_real_read_time(
    tmp_path, monkeypatch
):
    post_at = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    generated_at = post_at + timedelta(seconds=2)
    get_at = post_at + timedelta(seconds=3)
    clock = _set_clock(monkeypatch, post_at=post_at, generated_at=generated_at)
    monkeypatch.setattr(api_fixture, "NOW", post_at)
    service = _service(tmp_path)

    try:
        with api_fixture._client(service) as client:
            saved = _post(client)
            saved_product = saved["plan_product"]
            assert saved_product["status"] == "CURRENT"
            assert saved_product["consumed"] is True
            assert saved_product["run_readback"]["status"] == "VERIFIED"
            assert all(saved[key] is value for key, value in FLAGS.items())

            # No view, selection_date, or announcement_date: this is the normal
            # parent-page GET with router defaults, three seconds after POST.
            clock["now"] = get_at
            monkeypatch.setattr(api_fixture, "NOW", get_at)
            read = _get(client)

            assert read["date_bindings"] == {
                "plan_date": TARGET,
                "selection_date": TARGET,
                "announcement_date": previous_hk_session(TARGET),
            }
            assert read["plan_product"]["run_id"] == saved_product["run_id"]
            assert read["plan_product"]["status"] == "CURRENT"
            assert read["plan_product"]["consumed"] is True
            assert read["plan_product"]["run_readback"]["status"] == "VERIFIED"
            assert read["plan_product"]["run_readback"]["read_at"] == get_at.isoformat()
            assert read["plan_product"]["last_checked_at"] == get_at.isoformat()
            assert datetime.fromisoformat(read["plan_product"]["run_readback"]["read_at"]) >= datetime.fromisoformat(
                read["plan_product"]["generated_at"]
            )
            assert read["plan_context"]["research_cutoff"] == post_at.isoformat()
            assert read["input_identity"] == saved["input_identity"]

            wrong_selection = _get(client, selection_date="20261007", announcement_date="20261007")
            wrong_publication = _get(client, selection_date=TARGET, announcement_date="20261006")
            for wrong in (wrong_selection, wrong_publication):
                assert wrong["plan_context"]["research_cutoff"] == get_at.isoformat()
                assert wrong["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
                assert wrong["plan_product"]["consumed"] is False
                assert wrong["plan_product"]["run_id"] == saved_product["run_id"]

        # The no-save owner lane must begin from its actual later clock. It may
        # not borrow the sealed plan cutoff as a successful readback shortcut.
        preview_at = get_at + timedelta(seconds=1)
        preview = workspace_owner.get_workspace(
            service,
            TARGET,
            include_saved=False,
            view="auto",
            now=preview_at,
            selection_date=TARGET,
            announcement_date="20261007",
        )
        assert preview["plan_context"]["research_cutoff"] == preview_at.isoformat()
        assert "plan_product" not in preview
        assert preview["read_context"]["as_of"] == preview_at.isoformat()
    finally:
        service.close()


def test_future_auto_page_reads_its_exact_saved_evening_plan(tmp_path, monkeypatch):
    post_at = datetime(2026, 10, 8, 20, 0, tzinfo=HK)
    generated_at = post_at + timedelta(seconds=2)
    get_at = post_at + timedelta(seconds=3)
    clock = _set_clock(monkeypatch, post_at=post_at, generated_at=generated_at)
    monkeypatch.setattr(api_fixture, "NOW", post_at)
    service = _service(tmp_path)
    future = "20261009"

    try:
        with api_fixture._client(service) as client:
            saved = _post(client, future)
            clock["now"] = get_at
            monkeypatch.setattr(api_fixture, "NOW", get_at)
            read = _get(client, future)

        assert read["read_context"]["mode"] == "CURRENT_DYNAMIC_PREVIEW"
        assert read["plan_product"]["status"] == "CURRENT"
        assert read["plan_product"]["consumed"] is True
        assert read["plan_product"]["run_id"] == saved["plan_product"]["run_id"]
        assert read["date_bindings"] == {
            "plan_date": future,
            "selection_date": future,
            "announcement_date": previous_hk_session(future),
        }
        assert read["plan_context"]["research_cutoff"] == post_at.isoformat()
        assert read["plan_product"]["run_readback"]["read_at"] == get_at.isoformat()
    finally:
        service.close()


def test_verified_us_owner_source_revision_is_replayed_and_stays_stale(tmp_path, monkeypatch):
    from test_manager_us_mapping_research import _synthetic_us_payload

    post_at = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    generated_at = post_at + timedelta(seconds=2)
    get_at = post_at + timedelta(seconds=3)
    clock = _set_clock(monkeypatch, post_at=post_at, generated_at=generated_at)
    monkeypatch.setattr(api_fixture, "NOW", post_at)

    us_root = tmp_path / "synthetic-peripheral-owner"
    peripheral = ResearchPeripheralStore(us_root)
    us_session = latest_completed_session(post_at).session_date
    initially_published = peripheral.publish(_synthetic_us_payload(us_session, {"NVDA": 1.25}))
    reader = ResearchPeripheralUsMarketReader(us_root)
    service = _service(tmp_path, reader=reader)

    try:
        with api_fixture._client(service) as client:
            saved = _post(client)
            original_payload_sha = saved["us_market_attention"]["source_identity"]["payload_sha256"]
            assert original_payload_sha == initially_published["payload_sha256"]
            assert saved["us_market_attention"]["status"] == "READY"

            # A valid synthetic source-owner replacement exercises the real
            # store receipt, checksum validation, adapter, market bridge,
            # projection, and plan identity comparison in the GET below.
            replacement = _synthetic_us_payload(us_session, {"NVDA": 2.5})
            changed = peripheral.replace(
                replacement,
                expected_sha256=initially_published["payload_sha256"],
                reason="SYNTHETIC_REVIEW_FIXTURE_SOURCE_REVISION",
            )
            assert changed["replaced"] is True
            clock["now"] = get_at
            monkeypatch.setattr(api_fixture, "NOW", get_at)
            read = _get(client)

        assert read["us_market_attention"]["source_identity"]["status"] == "VERIFIED"
        assert read["us_market_attention"]["source_identity"]["payload_sha256"] == changed["payload_sha256"]
        assert read["us_market_attention"]["source_identity"]["payload_sha256"] != original_payload_sha
        assert read["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
        assert read["plan_product"]["consumed"] is False
        assert read["plan_product"]["run_id"] == saved["plan_product"]["run_id"]
        assert read["plan_context"]["research_cutoff"] == post_at.isoformat()
    finally:
        service.close()


def test_late_us_daily_owner_cycle_is_not_consumed_by_saved_plan_readback(tmp_path, monkeypatch):
    from test_manager_us_mapping_research import _synthetic_us_payload

    post_at = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    generated_at = post_at + timedelta(seconds=2)
    late_cycle_at = post_at + timedelta(seconds=4)
    get_at = post_at + timedelta(seconds=5)
    clock = _set_clock(monkeypatch, post_at=post_at, generated_at=generated_at)
    monkeypatch.setattr(api_fixture, "NOW", post_at)
    owner_clock = _set_module_clock(monkeypatch, us_mapping_research, late_cycle_at + timedelta(seconds=1))

    reviewed_unsigned = {
        "schema_version": "v4.manager_research.us_mapping_reviewed.v1",
        "target_trade_date": "20260930",
        "status": "TEST_FIXTURE_SYNTHETIC_REVIEW",
        "reviewed_at": post_at.isoformat(),
        "cards": [],
        **FLAGS,
    }
    reviewed = {**reviewed_unsigned, "artifact_sha256": digest(reviewed_unsigned)}
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(
        us_mapping_research,
        "_relation_available_at",
        lambda _reviewed: (post_at - timedelta(days=1), None),
    )

    us_root = tmp_path / "synthetic-peripheral-owner"
    peripheral = ResearchPeripheralStore(us_root)
    us_session = latest_completed_session(post_at).session_date
    peripheral.publish(_synthetic_us_payload(us_session, {}))
    service = _service(tmp_path, reader=ResearchPeripheralUsMarketReader(us_root))

    try:
        with api_fixture._client(service) as client:
            saved = _post(client)
            saved_run = saved["plan_product"]["run_id"]
            late_cycle = service.refresh_us_mapping_research(
                TARGET,
                now=late_cycle_at,
                execution_context={
                    "trigger_kind": "SCHEDULED",
                    "timing": "LATE_CATCHUP",
                    "scheduled_for": (post_at - timedelta(minutes=5)).isoformat(),
                    "trigger_id": "a" * 64,
                    "natural_run_verified": False,
                },
            )
            assert late_cycle["run_id"]
            assert late_cycle["status"] in {"VALID_EMPTY", "PARTIAL"}
            assert datetime.fromisoformat(late_cycle["generated_at"]) > post_at
            assert late_cycle["latest_attempt"]["trigger_id"] == "a" * 64

            clock["now"] = get_at
            owner_clock["now"] = get_at
            monkeypatch.setattr(api_fixture, "NOW", get_at)
            read = _get(client)

        assert read["plan_product"]["status"] == "CURRENT"
        assert read["plan_product"]["consumed"] is True
        assert read["plan_product"]["run_id"] == saved_run
        assert read["plan_product"]["run_readback"]["read_at"] == get_at.isoformat()
        reference = read["owner_chain"]["us_mapping_daily_plan_reference"]
        assert reference["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
        assert reference["run_id"] == late_cycle["run_id"]
        assert datetime.fromisoformat(reference["available_at"]) > post_at
        daily = read["us_mapping_research"]["daily_run"]
        assert daily["latest_attempt"]["run_id"] == late_cycle["run_id"]
        assert daily["latest_attempt_after_plan_cutoff"] is True
        assert daily["latest_attempt_affects_saved_plan"] is False
        assert all(read[key] is value for key, value in FLAGS.items())
    finally:
        service.close()

