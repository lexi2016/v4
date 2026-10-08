"""Independent probes of the US daily owner delta.

All prices, relations, timestamps, and expected mappings in this file are
synthetic TEST_FIXTURE data. The tests exercise the original
build_daily_run, ManagerResearchJobService.refresh_us_mapping_research,
SafeRoot product publication, and exact run readback. They also exercise the
ResearchPeripheralStore adapter with synthetic input. They do not verify live
Mac artifacts, actual PIT availability, or natural execution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from threading import Event, Lock
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

REVIEWER_DIR = Path(__file__).resolve().parent
if str(REVIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEWER_DIR))
from _source_root import source_root  # noqa: E402

REPO = source_root(__file__)
for import_root in (REPO, REPO / "upstreams"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from infrastructure.research_peripheral_store import (
    CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP,
    _CANONICAL_SYMBOLS,
    _MARKET_MAPPING_VERSION,
    _MARKET_SNAPSHOT_SCHEMA_VERSION,
    _SCHEMA_VERSION,
    ResearchPeripheralStore,
)
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import FLAGS, HK
from v4.manager_research import us_mapping_research
from v4.manager_research import workspace as workspace_module
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research import us_market_bridge


US = ZoneInfo("America/New_York")


def _synthetic_us_payload(session_date: str, positive_changes: dict[str, float]) -> dict:
    """Build one valid original-owner envelope from explicitly synthetic rows."""
    day = datetime.strptime(session_date, "%Y%m%d")
    captured = datetime(day.year, day.month, day.day, 16, 15, 3, tzinfo=US)
    captured_text = captured.isoformat()
    symbols = sorted(_CANONICAL_SYMBOLS)
    changes = {symbol: float(positive_changes.get(symbol, 0.0)) for symbol in symbols}
    quotes = []
    for symbol in symbols:
        pct = changes[symbol]
        previous = 100.0
        quotes.append({
            "symbol": symbol, "exchange": "US", "session_date": session_date,
            "session_time": "16:00:00", "last": previous * (1.0 + pct / 100.0),
            "previous_close": previous, "change_pct": pct,
            "provider": "ISOLATED_TEST_FIXTURE",
        })
    rows = []
    for definition in CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP:
        proxies = list(definition["proxy_symbols"])
        pct = sum(changes[symbol] for symbol in proxies) / len(proxies)
        rows.append({
            "label": definition["label"], "group": definition["group"],
            "mapping_type": definition["mapping_type"], "proxy_symbols": proxies,
            "available_symbols": proxies, "missing_symbols": [],
            "requested_symbol_count": len(proxies), "available_symbol_count": len(proxies),
            "coverage": {"available": len(proxies), "requested": len(proxies)},
            "coverage_pct": 100.0, "change_pct": pct, "pct_change": pct,
            "direction": "UP" if pct > 0 else "DOWN" if pct < 0 else "FLAT",
            "status": "READY", "quote_session_dates": [session_date],
            "quote_session_times": ["16:00:00"], "cannot_confirm": [],
        })
    response_sha = hashlib.sha256(json.dumps(
        {"fixture": True, "session_date": session_date, "changes": changes},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = {
        "schema_version": _MARKET_SNAPSHOT_SCHEMA_VERSION, "status": "READY",
        "source": "external_finance", "provider": "ISOLATED_TEST_FIXTURE",
        "source_response_sha256": response_sha, "capture_phase": "POST_CLOSE",
        "capture_session_date": session_date, "captured_at": captured_text,
        "generated_at": captured_text, "mapping_version": _MARKET_MAPPING_VERSION,
        "requested_symbol_count": len(symbols), "available_symbol_count": len(symbols),
        "provider_session_dates": [session_date], "provider_session_times": ["16:00:00"],
        "quotes": quotes, "rows": rows, "cannot_confirm": [],
        "recommendation_status": "RESEARCH_ONLY", "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    capture_id = f"synthetic-fixture-{session_date}"
    capture = {
        "us_session_date": session_date, "capture_phase": "POST_CLOSE",
        "session_timezone": "America/New_York",
        "capture_window_start": datetime(day.year, day.month, day.day, 16, 15, tzinfo=US).isoformat(),
        "capture_window_end": datetime(day.year, day.month, day.day, 16, 20, tzinfo=US).isoformat(),
        "capture_id": capture_id, "run_id": capture_id, "captured_at": captured_text,
        "capture_origin": "ORIGINAL_TIME_CAPTURE", "original_time_capture": True,
    }
    return {
        "schema_version": _SCHEMA_VERSION, "trade_date": session_date,
        "source": "external_finance", "status": "READY_EMPTY",
        "source_url": "https://fixture.invalid/synthetic-us-session",
        "fetched_at": (captured + timedelta(seconds=1)).isoformat(),
        "raw_item_count": 0, "item_count": 0, "overview": [], "details": [], "items": [],
        "cannot_confirm": [], "write_policy": "read_only", "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "market_snapshot_status": "READY", "market_snapshot": snapshot,
        "us_session_captures": [capture], "capture_origin": "ORIGINAL_TIME_CAPTURE",
        "original_time_capture": True,
    }


def _fixture_relations(monkeypatch, *, available_at: datetime) -> None:
    reviewed = {
        "schema_version": "TEST_FIXTURE",
        "artifact_sha256": "d" * 64,
        "cards": [{
            "daily_match_symbols": ["LITE"], "hk_symbol": "HK.06166",
            "hk_name": "Synthetic component peer", "research_priority": "PRIORITY",
            "relationship_type": "PRODUCT_PEER", "reason": "TEST_FIXTURE_SYNTHETIC_RELATION",
            "maturity": "TEST_FIXTURE", "limitations": ["synthetic only"],
            "official_sources": [],
        }],
    }
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(us_mapping_research, "_relation_available_at",
                        lambda _value: (available_at, None))


def _service(tmp_path: Path, reader) -> ManagerResearchJobService:
    master = tmp_path / "security-master"
    master.mkdir(exist_ok=True)
    return ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-state"), None, None,
        existing_research_source=None,
        workspace_security_master_root=master,
        workspace_us_market_reader=reader,
    )


class _CountingBlockingReader:
    def __init__(self, reader):
        self.reader = reader
        self.started = Event()
        self.release = Event()
        self.finished = Event()
        self._lock = Lock()
        self.active = 0
        self.max_active = 0

    def read_exact_session(self, session_date):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            if not self.release.wait(3):
                raise TimeoutError("TEST_FIXTURE_BLOCK_TIMEOUT")
            return self.reader.read_exact_session(session_date)
        finally:
            with self._lock:
                self.active -= 1
            self.finished.set()


class _ReentryBlockingReader:
    def __init__(self, reader):
        self.reader = reader
        self.first_entered = Event()
        self.second_entered = Event()
        self.release = Event()
        self._lock = Lock()
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def read_exact_session(self, session_date):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.calls == 1:
                self.first_entered.set()
            elif self.calls == 2:
                self.second_entered.set()
        try:
            if not self.release.wait(3):
                raise TimeoutError("TEST_FIXTURE_SOURCE_READ_BLOCKED")
            return self.reader.read_exact_session(session_date)
        finally:
            with self._lock:
                self.active -= 1


class _SyntheticExactReader:
    """Synthetic exact-session boundary accepted by the original bridge."""
    def __init__(self, sessions=("20261007", "20261008")):
        self.payloads = {
            session: _synthetic_us_payload(
                session, {"LITE": 5.25 if session == "20261007" else 7.5})
            for session in sessions
        }
        self.calls: list[str] = []

    def read_exact_session(self, session_date):
        self.calls.append(session_date)
        payload = self.payloads.get(session_date)
        if payload is None:
            return None, {"status": "NOT_MATERIALIZED", "session_date": session_date}
        # These are fixture hashes, not evidence of a real store receipt.
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload_sha = hashlib.sha256(raw).hexdigest()
        return payload, {
            "status": "VERIFIED", "session_date": session_date,
            "payload_sha256": payload_sha, "receipt_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        }


def _populated_reader(sessions=("20261007", "20261008")) -> _SyntheticExactReader:
    return _SyntheticExactReader(sessions)


class _StoreSpyReader:
    """Observe exact-session calls while retaining the original store adapter."""
    def __init__(self, reader):
        self.reader = reader
        self.calls: list[str] = []

    def read_exact_session(self, session_date):
        self.calls.append(session_date)
        return self.reader.read_exact_session(session_date)


def _call_owner(service, target: str, now: datetime, trigger_id: str, *, timeout_seconds=1.5):
    return service.refresh_us_mapping_research(
        target, now=now, timeout_seconds=timeout_seconds,
        execution_context={
            "trigger_kind": "SCHEDULED", "timing": "UNCLASSIFIED",
            "scheduled_for": "2026-10-08T06:30:00+08:00",
            "trigger_id": trigger_id, "natural_run_verified": False,
        },
    )


def _parse_aware(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_real_original_owner_retro_target_uses_target_bound_cutoff_and_not_next_us_session(tmp_path, monkeypatch):
    """A 10/9 recovery of target 10/8 must read only synthetic US session 10/7."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    spy = _populated_reader()
    service = _service(tmp_path, spy)
    actual_start = datetime(2026, 10, 9, 10, 5, tzinfo=HK)
    try:
        result = _call_owner(service, "20261008", actual_start, "1" * 64)
    finally:
        service.close()

    assert spy.calls == ["20261007"]
    assert result["target_trade_date"] == "20261008"
    assert result["us_session_date"] == "20261007"
    assert result["status"] == "COMPLETED"
    assert [(row["us_symbol"], row["hk_symbol"], row["change_pct"]) for row in result["matches"]] == [
        ("LITE", "HK.06166", 5.25),
    ]
    cutoff = _parse_aware(result["research_cutoff"])
    assert cutoff == datetime(2026, 10, 8, 23, 59, 59, 999999, tzinfo=HK)
    assert _parse_aware(result["generated_at"]) >= actual_start
    assert result["research_cutoff_policy"] == "TARGET_DATE_END_OF_DAY_RETROSPECTIVE"
    execution = result["execution_context"]
    assert execution["trigger_kind"] == "SCHEDULED"
    assert execution["timing"] == "RETROSPECTIVE"
    assert _parse_aware(execution["started_at"]) >= actual_start
    assert _parse_aware(execution["finished_at"]) >= _parse_aware(execution["started_at"])
    assert execution["natural_run_verified"] is False
    assert result["RESEARCH_ONLY"] is True and result["production_allowed"] is False
    assert result["buy_gate_updated"] is False and result["orders_sent"] is False


def test_TEST_FIXTURE_original_store_adapter_receipt_manifest_and_owner_readback(tmp_path, monkeypatch):
    """Use the real owner store/adapter with synthetic data under tmp_path only."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    data_root = tmp_path / "synthetic-peripheral-owner"
    peripheral = ResearchPeripheralStore(data_root)
    peripheral.publish(_synthetic_us_payload("20261007", {"LITE": 3.75}))
    peripheral.publish(_synthetic_us_payload("20261008", {"LITE": 8.5}))
    spy = _StoreSpyReader(ResearchPeripheralUsMarketReader(data_root))
    service = _service(tmp_path, spy)
    try:
        result = _call_owner(
            service, "20261008", datetime(2026, 10, 9, 10, 5, tzinfo=HK), "8" * 64)
        readback = us_mapping_research.read_workspace_mapping(service, "20261008")["daily_run"]
    finally:
        service.close()

    assert spy.calls == ["20261007"]
    assert result["status"] == "COMPLETED"
    assert result["source_identity"]["status"] == "VERIFIED"
    assert result["source_identity"]["payload_sha256"]
    assert result["source_identity"]["receipt_sha256"]
    assert result["source_identity"]["manifest_sha256"]
    assert result["us_session_date"] == "20261007"
    assert [(row["us_symbol"], row["change_pct"]) for row in result["matches"]] == [
        ("LITE", 3.75),
    ]
    assert readback["run_id"] == result["run_id"]
    assert readback["artifact_sha256"] == result["artifact_sha256"]


def test_retro_owner_does_not_fall_forward_to_only_late_us_session(tmp_path, monkeypatch):
    """Presence of 10/8 cannot substitute for the target-bound 10/7 source."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    spy = _populated_reader(sessions=("20261008",))
    service = _service(tmp_path, spy)
    try:
        result = _call_owner(
            service, "20261008", datetime(2026, 10, 9, 10, 5, tzinfo=HK), "2" * 64)
    finally:
        service.close()

    assert spy.calls == ["20261007"]
    assert result["status"] == "INPUT_MISSING"
    assert result["coverage"]["matched_us_symbol_count"] is None
    assert result["coverage"]["matched_hk_relation_count"] is None
    assert result["execution_context"]["timing"] == "RETROSPECTIVE"
    assert result["execution_context"]["natural_run_verified"] is False


def test_retro_owner_keeps_post_cutoff_registry_as_a_gap(tmp_path, monkeypatch):
    """A late registry cannot turn a historical relation into a target-day fact."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 9, 0, 5, tzinfo=HK))
    spy = _populated_reader()
    service = _service(tmp_path, spy)
    try:
        result = _call_owner(
            service, "20261008", datetime(2026, 10, 9, 10, 5, tzinfo=HK), "3" * 64)
    finally:
        service.close()

    assert spy.calls == ["20261007"]
    assert result["status"] == "PARTIAL"
    assert result["matches"] == []
    assert result["coverage"]["matched_us_symbol_count"] is None
    assert result["coverage"]["matched_hk_relation_count"] is None
    assert result["relation_artifact_sha256"] is None
    assert "US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF" in result["gaps"]


def test_recovered_trigger_is_idempotent_across_service_restart(tmp_path, monkeypatch):
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    reader = _populated_reader()
    spy = reader
    first_service = _service(tmp_path, spy)
    target_now = datetime(2026, 10, 9, 10, 5, tzinfo=HK)
    try:
        first = _call_owner(first_service, "20261008", target_now, "4" * 64)
        run_path = first_service.store.root / "us_mapping_research" / "20261008" / "runs" / f"{first['run_id']}.json"
        pointer_path = first_service.store.root / "us_mapping_research" / "20261008" / "latest.json"
        run_before = run_path.read_bytes()
        pointer_before = pointer_path.read_bytes()
    finally:
        first_service.close()

    class MustNotRead:
        def read_exact_session(self, _session_date):
            raise AssertionError("same trigger re-read the source after restart")

    second_service = _service(tmp_path, MustNotRead())
    try:
        second = _call_owner(second_service, "20261008", target_now, "4" * 64)
        assert second["run_id"] == first["run_id"]
        assert second["artifact_sha256"] == first["artifact_sha256"]
        assert run_path.read_bytes() == run_before
        assert pointer_path.read_bytes() == pointer_before
        assert len(list(run_path.parent.glob("*.json"))) == 1
    finally:
        second_service.close()


def test_distinct_attempt_reusing_same_inputs_keeps_attempt_metadata_current(tmp_path, monkeypatch):
    """A reused immutable product must not rewrite the later trigger as the first run."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    service = _service(tmp_path, _populated_reader())
    try:
        first_now = datetime.now(HK)
        first = _call_owner(service, "20261008", first_now, "8" * 64)
        second = _call_owner(
            service, "20261008", first_now + timedelta(seconds=10), "9" * 64)
        second_receipt = json.loads((service.store.root / "us_mapping_dispatch" / "20261008"
                                    / f"{'9' * 64}.json").read_bytes())
        latest_attempt = us_mapping_research.read_workspace_mapping(
            service, "20261008")["daily_run"]["latest_attempt"]

        assert second["run_id"] == first["run_id"]
        assert second_receipt["trigger_id"] == "9" * 64
        assert second_receipt["result"]["execution_context"]["trigger_id"] == "8" * 64
        assert second_receipt["attempt"]["execution_context"]["trigger_id"] == "9" * 64
        assert latest_attempt["trigger_id"] == "9" * 64
        assert latest_attempt["execution_context"]["trigger_id"] == "9" * 64
        assert second_receipt["finished_at"] >= second_receipt["started_at"]
    finally:
        service.close()


@pytest.mark.parametrize("pointer_mode", ["older", "newer"])
def test_crash_after_run_publish_reconciliation_orders_exact_same_date_pointer(
    tmp_path, monkeypatch, pointer_mode,
):
    """Recovery repairs an older pointer but never rolls back a newer pointer."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    service = _service(tmp_path, _populated_reader())
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    try:
        prior = _call_owner(service, "20261008", now, "c" * 64)
        target = "20261008"
        trigger_id = "d" * 64
        prior_at = datetime.fromisoformat(prior["generated_at"])
        recovered_started = prior_at + timedelta(seconds=1)
        recovered_finished = prior_at + timedelta(seconds=2)
        retry_at = prior_at + timedelta(seconds=3)
        run_id = "e" * 32
        run = json.loads((service.store.root / "us_mapping_research" / target
                          / "runs" / f"{prior['run_id']}.json").read_bytes())
        run["run_id"] = run_id
        run["input_identity"] = "f" * 64
        run["generated_at"] = recovered_finished.isoformat(timespec="microseconds")
        run["execution_context"] = {
            **run["execution_context"],
            "trigger_id": trigger_id,
            "started_at": recovered_started.isoformat(timespec="microseconds"),
            "finished_at": recovered_finished.isoformat(timespec="microseconds"),
        }
        run["artifact_sha256"] = us_mapping_research.sha256_json(
            {key: value for key, value in run.items() if key != "artifact_sha256"})
        service.store._io.write_bytes(
            f"us_mapping_research/{target}/runs/{run_id}.json",
            json.dumps(run, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            require_absent=True)
        expected_latest_run_id = run_id
        if pointer_mode == "newer":
            newer_id = "f" * 32
            newer = dict(run)
            newer["run_id"] = newer_id
            newer["input_identity"] = "1" * 64
            newer_generated = recovered_finished + timedelta(seconds=1)
            newer["generated_at"] = newer_generated.isoformat(timespec="microseconds")
            newer["execution_context"] = {
                **newer["execution_context"],
                "trigger_id": "9" * 64,
                "started_at": recovered_finished.isoformat(timespec="microseconds"),
                "finished_at": newer_generated.isoformat(timespec="microseconds"),
            }
            newer["artifact_sha256"] = us_mapping_research.sha256_json(
                {key: value for key, value in newer.items() if key != "artifact_sha256"})
            service.store._io.write_bytes(
                f"us_mapping_research/{target}/runs/{newer_id}.json",
                json.dumps(newer, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
                require_absent=True)
            newer_pointer = {
                "schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
                "target_trade_date": target, "run_id": newer_id,
                "artifact_sha256": newer["artifact_sha256"], **FLAGS,
            }
            service.store._io.write_bytes(
                f"us_mapping_research/{target}/latest.json",
                json.dumps(newer_pointer, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode())
            expected_latest_run_id = newer_id
        started = us_mapping_research._seal_dispatch({
            "schema_version": us_mapping_research.DISPATCH_SCHEMA,
            "state": "RUNNING", "target_trade_date": target,
            "trigger_id": trigger_id,
            "started_at": recovered_started.isoformat(timespec="microseconds"),
            "budget_seconds": 5.0,
            "owner": "ManagerResearchJobService.refresh_us_mapping_research",
            "execution_context": {"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP"},
            **FLAGS,
        })
        service.store._io.write_bytes(
            f"us_mapping_dispatch/{target}/{trigger_id}.started.json",
            json.dumps(started, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            require_absent=True)

        recovered = _call_owner(
            service, target, retry_at, trigger_id)
        exact_readback = us_mapping_research.read_workspace_mapping(service, target)["daily_run"]

        assert recovered["run_id"] == run_id
        assert exact_readback["run_id"] == expected_latest_run_id, (
            "reconciliation must repair an older pointer but preserve a newer committed pointer")
        if pointer_mode == "older":
            assert exact_readback["artifact_sha256"] == run["artifact_sha256"]
    finally:
        service.close()


def test_timed_out_real_builder_cannot_publish_late_and_keeps_only_one_reader_slot(tmp_path, monkeypatch):
    """The injected source boundary blocks the real builder; it does not mock it."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    blocked = _CountingBlockingReader(_populated_reader())
    service = _service(tmp_path, blocked)
    now = datetime(2026, 10, 8, 6, 31, tzinfo=HK)
    try:
        started_at = time.monotonic()
        first = _call_owner(service, "20261008", now, "5" * 64, timeout_seconds=0.05)
        elapsed = time.monotonic() - started_at
        assert blocked.started.wait(0.5)
        assert elapsed < 1.0
        assert first["status"] == "FAILED"
        assert "US_MAPPING_OWNER_READ_TIMEOUT" in first["gaps"]
        assert not (service.store.root / "us_mapping_research" / "20261008" / "latest.json").exists()

        second_start = time.monotonic()
        second = _call_owner(service, "20261008", now, "6" * 64, timeout_seconds=0.05)
        assert time.monotonic() - second_start < 1.0
        assert second["status"] == "FAILED"
        assert "US_MAPPING_OWNER_READ_BUSY" in second["gaps"]
        assert blocked.max_active == 1

        blocked.release.set()
        assert blocked.finished.wait(1.0)
        assert not (service.store.root / "us_mapping_research" / "20261008" / "latest.json").exists()
    finally:
        blocked.release.set()
        service.close()


def test_same_trigger_timeout_retry_preserves_full_unknown_dto(tmp_path, monkeypatch):
    """Terminal dispatch replay must retain the original failure DTO contract."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    blocked = _CountingBlockingReader(_populated_reader())
    service = _service(tmp_path, blocked)
    target = "20261008"
    trigger_id = "7" * 64
    now = datetime(2026, 10, 8, 6, 31, tzinfo=HK)
    try:
        first = _call_owner(service, target, now, trigger_id, timeout_seconds=0.05)
        assert blocked.started.wait(0.5)
        assert first["schema_version"] == us_mapping_research.DAILY_SCHEMA
        assert first["target_trade_date"] == target
        assert first["matches"] == []
        assert first["coverage"]["matched_us_symbol_count"] is None
        assert first["coverage"]["matched_hk_relation_count"] is None

        replay = _call_owner(service, target, now, trigger_id, timeout_seconds=0.05)
        assert replay["schema_version"] == us_mapping_research.DAILY_SCHEMA
        assert replay["target_trade_date"] == target
        assert replay["status"] == "FAILED"
        assert replay["matches"] == []
        assert replay["coverage"]["matched_us_symbol_count"] is None
        assert replay["coverage"]["matched_hk_relation_count"] is None
        assert replay["execution_status"] == first["execution_status"]
        assert replay["execution_context"]["trigger_id"] == trigger_id
        assert blocked.max_active == 1
    finally:
        blocked.release.set()
        service.close()


def test_pointer_publish_budget_timeout_does_not_look_like_verified_daily_success(tmp_path, monkeypatch):
    """A committed pointer without terminal owner receipt is not a completed attempt."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    service = _service(tmp_path, _populated_reader())
    original_write = service.store._io.write_bytes
    pointer_path = "us_mapping_research/20261008/latest.json"

    def delayed_pointer_write(relative, data, **kwargs):
        result = original_write(relative, data, **kwargs)
        if relative == pointer_path:
            # SafeRoot's single write is not preemptible. Expire the very
            # short synthetic owner budget after the durable pointer write.
            time.sleep(0.08)
        return result

    monkeypatch.setattr(service.store._io, "write_bytes", delayed_pointer_write)
    try:
        owner = _call_owner(
            service, "20261008", datetime(2026, 10, 8, 6, 31, tzinfo=HK), "b" * 64,
            timeout_seconds=0.05)
        readback = us_mapping_research.read_workspace_mapping(service, "20261008")["daily_run"]

        assert owner["status"] == "FAILED"
        assert owner["execution_status"] == "US_MAPPING_OWNER_BUDGET_EXHAUSTED"
        assert readback["run_id"] is not None
        assert readback["status"] == "CANNOT_CONFIRM"
        assert readback["latest_attempt"]["state"] == "PUBLISHING"
        assert readback["run_readback"]["status"] == "CANNOT_CONFIRM"
        assert readback["run_readback"]["artifact_status"] == "VERIFIED"
        assert readback["saved_product_run_readback_status"] == "VERIFIED"
        saved = us_mapping_research._read_exact_run(
            service.store, "20261008", readback["run_id"], readback["artifact_sha256"])
        assert saved["execution_context"]["trigger_id"] == "b" * 64
        assert readback["latest_attempt"]["status"] == "CANNOT_CONFIRM"
        assert readback["latest_attempt"]["state"] == "PUBLISHING"
        assert readback["latest_attempt"]["execution_status"] == "US_MAPPING_DISPATCH_RECONCILIATION_REQUIRED"
        assert readback["latest_attempt"]["run_id"] == readback["run_id"]
    finally:
        service.close()


def test_timed_out_us_owner_does_not_reenter_reader_from_real_plan_owner_or_miss_deadline(
    tmp_path, monkeypatch,
):
    """A timed-out pure builder must not make the next real plan call the same reader again."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    blocked = _ReentryBlockingReader(_populated_reader())
    service = _service(tmp_path, blocked)
    target = "20261008"
    try:
        failed = _call_owner(
            service, target, datetime(2026, 10, 8, 6, 30, tzinfo=HK), "5" * 64,
            timeout_seconds=0.05)
        assert blocked.first_entered.wait(0.5)
        assert failed["status"] == "FAILED"
        assert "US_MAPPING_OWNER_READ_TIMEOUT" in failed["gaps"]

        plan_now = datetime(2026, 10, 8, 9, 28, tzinfo=HK)
        plan_start = time.monotonic()
        deadline = plan_now + timedelta(seconds=0.2)
        monkeypatch.setattr(workspace_module, "_now", lambda: (
            plan_now + timedelta(seconds=time.monotonic() - plan_start)
        ).astimezone(timezone.utc).isoformat(timespec="microseconds"))

        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)
        before = time.monotonic()
        future = executor.submit(
            service.refresh_workspace_plan, target,
            execution_kind="SCHEDULED_PREOPEN", now=plan_now, deadline=deadline)
        try:
            second_call = blocked.second_entered.wait(0.15)
            if second_call:
                # Keep the simulated source blocked beyond the pre-open owner budget.
                time.sleep(0.25)
            blocked.release.set()
            plan_error = None
            try:
                result = future.result(timeout=3)
            except Exception as exc:  # the receipt remains inspectable below
                result = None
                plan_error = f"{type(exc).__name__}:{exc}"
            elapsed = time.monotonic() - before
        finally:
            blocked.release.set()
            executor.shutdown(wait=True)

        assert not blocked.second_entered.is_set(), (
            "the original workspace owner re-entered the timed-out US source on the synchronous plan path; "
            f"calls={blocked.calls}, max_active={blocked.max_active}, elapsed={elapsed:.3f}s, "
            f"plan_error={plan_error}")
        assert blocked.calls == 1
        assert blocked.max_active == 1
        assert elapsed < 0.5
        assert plan_error is None
        assert result["plan_product"]["consumed"] is True
        assert result["us_market_attention"]["status"] in {
            "INPUT_MISSING", "CANNOT_CONFIRM", "SOURCE_FAILED", "READY", "PARTIAL",
        }
    finally:
        blocked.release.set()
        service.close()


def test_source_exception_does_not_change_other_owner_artifacts(tmp_path, monkeypatch):
    class BrokenReader:
        def read_exact_session(self, _session_date):
            raise OSError("TEST_FIXTURE_SOURCE_OFFLINE")

    service = _service(tmp_path, BrokenReader())
    unrelated = service.store.root / "workspace_announcements" / "20261008" / "latest.json"
    service.store._io.write_bytes(
        "workspace_announcements/20261008/latest.json", b'{"fixture":"preserve"}')
    before = unrelated.read_bytes()
    try:
        result = _call_owner(
            service, "20261008", datetime(2026, 10, 8, 6, 30, tzinfo=HK), "7" * 64)
        assert result["status"] == "FAILED"
        assert result["coverage"]["matched_us_symbol_count"] is None
        assert result["coverage"]["matched_hk_relation_count"] is None
        assert unrelated.read_bytes() == before
        assert not (service.store.root / "workspace_plans" / "20261008" / "latest.json").exists()
    finally:
        service.close()


def test_same_plan_cutoff_keeps_saved_mapping_and_exposes_later_attempt_without_write(
    tmp_path, monkeypatch,
):
    plan_store = ManagerResearchStore(tmp_path / "manager")
    plan_service = SimpleNamespace(store=plan_store)
    cutoff = datetime(2026, 10, 8, 9, 28, tzinfo=HK)
    monkeypatch.setattr(workspace_module, "_now", lambda: "2026-10-08T01:28:01+00:00")
    saved_daily = {
        "schema_version": "v4.manager_research.us_mapping_daily_run.v1",
        "status": "COMPLETED", "target_trade_date": "20261008",
        "run_id": "a" * 32, "artifact_sha256": "b" * 64,
        "generated_at": "2026-10-08T06:00:00+08:00",
        "matches": [{"us_symbol": "NVDA", "hk_symbol": "0981"}],
        "gaps": [], **FLAGS,
    }
    initial = {
        "target_trade_date": "20261008", "input_identity": "c" * 64,
        "semantic_version": "TEST_FIXTURE", "plan_context": {"research_cutoff": cutoff.isoformat()},
        "gaps": [], "stocks": [], "existing_material_coverage": {}, "summary": {},
        "lanes": [], "us_mapping_research": {"daily_run": saved_daily}, **FLAGS,
    }
    monkeypatch.setattr(workspace_module, "get_workspace", lambda *_a, **_kw: initial)
    stored = workspace_module.refresh_workspace_plan(plan_service, "20261008", now=cutoff)
    latest_path = plan_store.root / "workspace_plans" / "20261008" / "latest.json"
    run_path = plan_store.root / "workspace_plans" / "20261008" / f"{stored['plan_product']['run_id']}.json"
    attempt_path = (plan_store.root / "workspace_plan_runs" / "20261008"
                    / f"{stored['plan_product']['run_id']}.json")
    before = {path: path.read_bytes() for path in (latest_path, run_path, attempt_path)}

    later_attempt = {
        "status": "FAILED", "trigger_id": "d" * 64,
        "finished_at": "2026-10-08T10:00:00+08:00",
        "execution_context": {"trigger_id": "d" * 64, "timing": "LATE_CATCHUP"},
    }
    current = dict(initial)
    current["us_mapping_research"] = {"daily_run": {
        **saved_daily, "latest_attempt": later_attempt,
    }}
    result = workspace_module._readback_plan(plan_store, "20261008", current)

    daily = result["us_mapping_research"]["daily_run"]
    assert result["plan_product"]["consumed"] is True
    assert result["plan_product"]["run_id"] == stored["plan_product"]["run_id"]
    assert daily["run_id"] == saved_daily["run_id"]
    assert daily["matches"] == saved_daily["matches"]
    assert daily["latest_attempt"]["trigger_id"] == "d" * 64
    assert daily["latest_attempt_after_plan_cutoff"] is True
    assert daily["latest_attempt_affects_saved_plan"] is False
    assert {path: path.read_bytes() for path in before} == before


def test_saved_plan_attempt_overlay_uses_saved_cutoff_not_current_get_cutoff(tmp_path, monkeypatch):
    """A 09:30 attempt follows a 09:00 saved plan even when GET runs at 10:00."""
    plan_store = ManagerResearchStore(tmp_path / "manager")
    plan_service = SimpleNamespace(store=plan_store)
    saved_cutoff = datetime(2026, 10, 8, 9, 0, tzinfo=HK)
    current_cutoff = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    monkeypatch.setattr(workspace_module, "_now", lambda: "2026-10-08T01:01:00+00:00")
    saved_daily = {
        "schema_version": "v4.manager_research.us_mapping_daily_run.v1",
        "status": "COMPLETED", "target_trade_date": "20261008",
        "run_id": "a" * 32, "artifact_sha256": "b" * 64,
        "generated_at": "2026-10-08T08:45:00+08:00",
        "matches": [{"us_symbol": "NVDA", "hk_symbol": "0981"}],
        "gaps": [], **FLAGS,
    }
    saved_workspace = {
        "target_trade_date": "20261008", "input_identity": "c" * 64,
        "semantic_version": "TEST_FIXTURE",
        "plan_context": {"research_cutoff": saved_cutoff.isoformat()},
        "gaps": [], "stocks": [], "existing_material_coverage": {}, "summary": {},
        "lanes": [], "us_mapping_research": {"daily_run": saved_daily}, **FLAGS,
    }
    monkeypatch.setattr(workspace_module, "get_workspace", lambda *_a, **_kw: saved_workspace)
    stored = workspace_module.refresh_workspace_plan(
        plan_service, "20261008", now=saved_cutoff)
    run_path = plan_store.root / "workspace_plans" / "20261008" / (
        stored["plan_product"]["run_id"] + ".json")
    before = run_path.read_bytes()

    current = dict(saved_workspace)
    current["plan_context"] = {"research_cutoff": current_cutoff.isoformat()}
    current["us_mapping_research"] = {"daily_run": {
        **saved_daily,
        "latest_attempt": {
            "status": "FAILED", "trigger_id": "d" * 64,
            "finished_at": "2026-10-08T09:30:00+08:00",
            "execution_context": {"trigger_id": "d" * 64, "timing": "LATE_CATCHUP"},
        },
    }}
    result = workspace_module._readback_plan(plan_store, "20261008", current)

    daily = result["us_mapping_research"]["daily_run"]
    assert daily["latest_attempt"]["trigger_id"] == "d" * 64
    assert daily["latest_attempt_after_plan_cutoff"] is True
    assert daily["latest_attempt_affects_saved_plan"] is False
    assert run_path.read_bytes() == before


def test_retro_target_separates_actual_plan_us_session_from_target_bound_mapping_and_pit(
    tmp_path, monkeypatch,
):
    """10/9 as-of data and 10/8 mapping evidence keep explicit independent dates."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    reader = _populated_reader()
    service = _service(tmp_path, reader)
    date = "20261008"
    actual_now = datetime(2026, 10, 9, 10, 5, tzinfo=HK)
    try:
        current_plan_context = plan_context(date, now=actual_now)
        current_us_market = us_market_bridge.project_us_market(reader, date, current_plan_context)
        daily = _call_owner(service, date, actual_now, "a" * 64)
        preopen_context = plan_context(date, now=datetime(2026, 10, 8, 9, 28, tzinfo=HK))
        _, preopen_reference, preopen_identities = workspace_module._daily_mapping_plan_reference(
            service, date, preopen_context)
        _, retrospective_reference, retrospective_identities = workspace_module._daily_mapping_plan_reference(
            service, date, current_plan_context)

        assert current_plan_context["research_cutoff"] == actual_now.isoformat()
        assert current_us_market["expected_us_session"] == "20261008"
        assert daily["us_session_date"] == "20261007"
        assert daily["research_cutoff"] == "2026-10-08T23:59:59.999999+08:00"
        assert daily["execution_context"]["timing"] == "RETROSPECTIVE"
        assert daily["generated_at"].startswith("2026-10-09T")
        assert preopen_reference["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
        assert preopen_identities == []
        assert retrospective_reference["status"] == "CONSUMED"
        assert retrospective_identities == [daily["artifact_sha256"]]
    finally:
        service.close()


@pytest.mark.parametrize("scan_mode", ["equivalent", "reconcile"])
def test_us_same_budget_scan_stops_before_run_directory_reads_exhaust_owner_budget(
    tmp_path, monkeypatch, scan_mode,
):
    """Slow bounded SafeRoot reads must not turn a 120ms US budget into a long tail."""
    _fixture_relations(monkeypatch, available_at=datetime(2026, 10, 5, 16, 18, tzinfo=HK))
    service = _service(tmp_path, _populated_reader())
    base_now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    try:
        # Make the matching immutable run sort after all changed-input rows so
        # the equivalent-run path must actually traverse its bounded history.
        with monkeypatch.context() as scoped:
            scoped.setattr(us_mapping_research, "uuid4",
                           lambda: SimpleNamespace(hex="f" * 32))
            base = _call_owner(service, "20261008", base_now, "9" * 64)
        runs_dir = service.store.root / "us_mapping_research" / "20261008" / "runs"
        template = json.loads((runs_dir / f"{base['run_id']}.json").read_bytes())
        for index in range(20):
            duplicate = dict(template)
            duplicate["run_id"] = f"{index:032x}"
            duplicate["input_identity"] = hashlib.sha256(f"other-input-{index}".encode()).hexdigest()
            unsigned = {key: value for key, value in duplicate.items() if key != "artifact_sha256"}
            duplicate["artifact_sha256"] = us_mapping_research.sha256_json(unsigned)
            raw = json.dumps(duplicate, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()
            service.store._io.write_bytes(
                f"us_mapping_research/20261008/runs/{duplicate['run_id']}.json",
                raw, require_absent=True)

        original_read_bytes = service.store._io.read_bytes
        slow_reads = 0

        def slow_run_read(relative, *, max_bytes=None):
            nonlocal slow_reads
            if relative.startswith("us_mapping_research/20261008/runs/") and relative.endswith(".json"):
                slow_reads += 1
                time.sleep(0.03)
            return original_read_bytes(relative, max_bytes=max_bytes)

        monkeypatch.setattr(service.store._io, "read_bytes", slow_run_read)
        probe_trigger = "a" * 64 if scan_mode == "equivalent" else "b" * 64
        if scan_mode == "reconcile":
            started = us_mapping_research._seal_dispatch({
                "schema_version": us_mapping_research.DISPATCH_SCHEMA,
                "state": "RUNNING", "target_trade_date": "20261008",
                "trigger_id": probe_trigger,
                "started_at": base_now.isoformat(), "budget_seconds": 0.12,
                "owner": "ManagerResearchJobService.refresh_us_mapping_research",
                "execution_context": {"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP"},
                **FLAGS,
            })
            relative = f"us_mapping_dispatch/20261008/{probe_trigger}.started.json"
            raw_started = json.dumps(started, sort_keys=True, separators=(",", ":")).encode()
            service.store._io.write_bytes(relative, raw_started, require_absent=True)

        before = time.monotonic()
        result = _call_owner(
            service, "20261008", datetime(2026, 10, 8, 6, 31, tzinfo=HK), probe_trigger,
            timeout_seconds=0.12)
        elapsed = time.monotonic() - before

        max_budget_reads = int(0.12 / 0.03) + 2  # budgeted reads + one uninterruptible read + readback
        assert slow_reads <= max_budget_reads, (
            f"run-directory scan read {slow_reads} artifacts past its 120ms budget")
        assert elapsed < 0.45, f"owner exceeded 120ms budget by scanning for {elapsed:.3f}s"
        assert result["status"] in {"COMPLETED", "FAILED"}
    finally:
        service.close()
