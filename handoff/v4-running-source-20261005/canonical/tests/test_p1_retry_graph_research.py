from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

# See the date-boundary tests for why the compatibility module alias is
# installed before Starlette's TestClient is imported by any dependent test.
sys.modules.setdefault("httpx2", httpx)

from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_store import HourlyResearchStore
from infrastructure.runtime_graph.http_client import API_PORT, make_http_get, validate_api_base
from infrastructure.runtime_graph.service import RuntimeGraphService
from ops import run_v35_macos_scheduler as scheduler
from ops import run_scheduled_slot


def _failed_receipt(root: Path, *, retry_after: str) -> None:
    target = root / "receipts" / "live" / "20260817" / "1300"
    target.mkdir(parents=True, exist_ok=True)
    (target / "retry.dispatch-receipt.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "failure_class": "NETWORK",
                "retry_after": retry_after,
                "release_id": "release-1",
                "upstream_fingerprint": "upstream-1",
                "attempt": 2,
                "finished_at": "2026-08-17T04:59:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_exact_observed_slot_is_retry_gated_and_returns_no_due(
    tmp_path: Path,
) -> None:
    _failed_receipt(tmp_path, retry_after="2026-08-17T05:05:00Z")

    due = scheduler.resolve_due_slot(
        ledger_root=tmp_path,
        now=datetime.fromisoformat("2026-08-17T13:00:00+08:00"),
        release_id="release-1",
        upstream_fingerprint="upstream-1",
    )

    assert due["slot"] is None
    assert due["status"] == "RETRY_BACKOFF"
    assert due["retry_blocked"] is True


def test_exact_observed_slot_reopens_when_release_changes(tmp_path: Path) -> None:
    _failed_receipt(tmp_path, retry_after="2026-08-17T05:05:00Z")

    due = scheduler.resolve_due_slot(
        ledger_root=tmp_path,
        now=datetime.fromisoformat("2026-08-17T13:00:00+08:00"),
        release_id="release-2",
        upstream_fingerprint="upstream-1",
    )

    assert due["slot"] == "1300"
    assert "retry_blocked" not in due


def test_scheduler_does_not_call_runner_for_exact_retry_backoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260817", "1300"))
    monkeypatch.setattr(
        scheduler,
        "resolve_due_slot",
        lambda **_kwargs: {
            "business_date": "20260817",
            "observed_slot": "1300",
            "slot": None,
            "catchup": False,
            "lag_minutes": 0,
            "retry_blocked": True,
            "status": "RETRY_BACKOFF",
        },
    )
    called = False

    def should_not_run(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("retry_backoff must not dispatch")

    monkeypatch.setattr(scheduler, "run_scheduled_slot", should_not_run)

    assert scheduler.main(
        ["--data-root", str(tmp_path / "data"), "--ledger-root", str(tmp_path / "ledger")]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert called is False
    assert payload["status"] == "RETRY_BACKOFF"


def test_scheduler_and_slot_envelopes_have_typed_metadata_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("V35_RELEASE_ID", "V35_UPSTREAM_FINGERPRINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260817", "1323"))
    monkeypatch.setattr(
        scheduler,
        "resolve_due_slot",
        lambda **_kwargs: {
            "business_date": "20260817",
            "observed_slot": "1323",
            "slot": "1300",
            "catchup": True,
            "lag_minutes": 23,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "compute_dates",
        lambda **_kwargs: {
            "business_date": "20260817",
            "scheduled_date": "20260817",
            "target_date": "20260817",
        },
    )
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_slot",
        lambda **_kwargs: {
            "status": "SUCCEEDED",
            "slot": "1300",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )

    assert scheduler.main(
        ["--data-root", str(tmp_path / "data"), "--ledger-root", str(tmp_path / "ledger")]
    ) == 0
    scheduler_payload = json.loads(capsys.readouterr().out)
    for field in ("failure_class", "retry_after", "release_id", "upstream_fingerprint"):
        assert scheduler_payload[field] is None
    assert scheduler_payload["attempt"] == 0

    monkeypatch.setattr(
        run_scheduled_slot,
        "run_scheduled_slot",
        lambda **_kwargs: {
            "status": "SUCCEEDED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    monkeypatch.setattr(run_scheduled_slot, "compute_dates", lambda **_kwargs: {
        "business_date": "20260817",
        "scheduled_date": "20260817",
        "target_date": "20260817",
    })
    assert run_scheduled_slot.main(
        ["--slot", "1300", "--date", "20260817", "--data-root", str(tmp_path / "data")]
    ) == 0
    slot_payload = json.loads(capsys.readouterr().out)
    for field in ("failure_class", "retry_after", "release_id", "upstream_fingerprint"):
        assert slot_payload[field] is None
    assert slot_payload["attempt"] == 0


def test_runtime_graph_current_client_is_bound_to_8873() -> None:
    assert API_PORT == 8873
    assert validate_api_base("http://127.0.0.1:8873") == "http://127.0.0.1:8873"
    with pytest.raises(ValueError, match="API_BASE_UNSAFE"):
        validate_api_base("http://127.0.0.1:8872")
    assert make_http_get
    assert RuntimeGraphService.collect.__kwdefaults__["api_base"] == "http://127.0.0.1:8873"
    assert RuntimeGraphService.rebuild.__kwdefaults__["api_base"] == "http://127.0.0.1:8873"


def test_hourly_lane_exact_and_latest_use_verified_slot_methods(tmp_path: Path) -> None:
    # The implementation test intentionally exercises the production runner
    # and ResearchLaneSource, not a fake source seam.
    from test_hourly_research_runner import _source, _write_source
    from ops.run_hourly_research import run_hourly_research_file

    for slot in ("1200", "1300"):
        payload = _source("20260820")
        payload["source_manifest"]["hourly_slot"] = slot
        source = tmp_path / f"{slot}.json"
        _write_source(source, payload)
        run_hourly_research_file(
            data_root=tmp_path / "data",
            source=source,
            business_date="20260820",
            target_date="20260820",
            slot=slot,
            mode="LIVE",
        )

    store = HourlyResearchStore(tmp_path / "data")
    assert store.list_slots("20260820", mode="LIVE") == ["1200", "1300"]
    slot, payload = store.read_latest_for_date("20260820", mode="LIVE")
    assert slot == "1300"
    assert payload["archive_date"] == "20260820"

    lane = ResearchLaneSource(tmp_path / "data")
    exact_payload, exact_slot, count = lane.read_exact_lane("20260820")
    assert exact_payload is not None
    assert exact_slot == "1300"
    assert count == 2
    latest_payload, latest_slot, latest_count = lane.read_latest_lane()
    assert latest_payload is not None
    assert latest_payload["archive_date"] == "20260820"
    assert latest_slot == "1300"
    assert latest_count == 2
    assert lane.read_exact_lane("20260821") == (None, "", 0)


def test_hourly_lane_rejects_tampered_exact_slot(tmp_path: Path) -> None:
    from test_hourly_research_runner import _source, _write_source
    from ops.run_hourly_research import run_hourly_research_file

    payload = _source("20260820")
    source = tmp_path / "1200.json"
    _write_source(source, payload)
    run_hourly_research_file(
        data_root=tmp_path / "data",
        source=source,
        business_date="20260820",
        target_date="20260820",
        slot="1200",
        mode="LIVE",
    )
    receipt = tmp_path / "data" / "receipts" / "research" / "hourly" / "live" / "20260820" / "1200.json"
    broken = json.loads(receipt.read_text(encoding="utf-8"))
    broken["payload_sha256"] = "0" * 64
    receipt.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest or receipt"):
        HourlyResearchStore(tmp_path / "data").read_latest_for_date("20260820", mode="LIVE")


def test_hourly_store_is_date_bound_when_latest_points_to_another_date(
    tmp_path: Path,
) -> None:
    from test_hourly_research_runner import _source, _write_source
    from ops.run_hourly_research import run_hourly_research_file

    payload = _source("20260820")
    source = tmp_path / "1200.json"
    _write_source(source, payload)
    run_hourly_research_file(
        data_root=tmp_path / "data",
        source=source,
        business_date="20260820",
        target_date="20260820",
        slot="1200",
        mode="LIVE",
    )

    store = HourlyResearchStore(tmp_path / "data")
    assert store.list_slots("20260821", mode="LIVE") == []
    assert store.read_latest_for_date("20260821", mode="LIVE") is None
