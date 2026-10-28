"""Offline end-to-end checks for NYSE-gated US capture provenance."""
from __future__ import annotations

import contextlib
import hashlib
import io
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.http_transport import FetchResult, ProxyAwareHTTPTransport
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)
from ops import us_market_digest


ROOT = Path(__file__).resolve().parents[1]
SESSION = "20260924"
CAPTURED_AT = "2026-09-24T13:00:30Z"


def _fixed_capture_clock(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls.fromisoformat("2026-09-24T09:00:30-04:00")
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(us_market_digest, "datetime", FixedDateTime)

    def fetch(_self, url, *, timeout=None, **_kwargs):
        body = b"<rss><channel></channel></rss>"
        return FetchResult(
            body,
            {
                "status": "READY",
                "source": "SYNTHETIC_TEST_TRANSPORT",
                "source_url": url,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )

    monkeypatch.setattr(ProxyAwareHTTPTransport, "fetch", fetch)


def test_real_cli_and_dispatcher_distinguish_first_capture_from_idempotent_reuse(
    tmp_path: Path, monkeypatch
):
    _fixed_capture_clock(monkeypatch)
    invocations = []

    def process(command, *, cwd, timeout_seconds, env):
        assert command[1:3] == ["-m", "ops.us_market_digest"]
        invocations.append(tuple(command))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = us_market_digest.main(command[3:])
        return subprocess.CompletedProcess(
            command, returncode, stdout.getvalue(), stderr.getvalue()
        )

    data_root = tmp_path / "owned-data"
    registry = FixedExecutorRegistry(data_root=data_root, repo_root=ROOT, runner=process)
    request = DispatchRequest(
        scheduled_date=SESSION,
        business_date=SESSION,
        target_date=SESSION,
        slot="2100",
        mode=DispatchMode.LIVE,
    )

    first = registry._us_market_digest(request)
    assert first["status"] == "SUCCEEDED", first
    assert first["receipt_verified"] is True
    assert first["capture_performed"] is True
    assert first["new_capture_verified"] is True
    assert first["capture_reused"] is False
    assert first["capture_replaced"] is False
    assert first["capture_before_payload_sha256"] is None
    assert first["capture_after_payload_sha256"] == first["payload_sha256"]
    assert first["capture_before_receipt_sha256"] is None
    assert first["capture_after_receipt_sha256"] is not None
    assert first["capture_captured_at"] == CAPTURED_AT
    assert first["data_update_status"] == "EXACT_NEW_CAPTURE_VERIFIED"

    second = registry._us_market_digest(request)
    assert second["status"] == "SUCCEEDED", second
    assert second["receipt_verified"] is True
    assert second["capture_performed"] is False
    assert second["new_capture_verified"] is False
    assert second["capture_reused"] is True
    assert second["capture_replaced"] is False
    assert second["capture_before_payload_sha256"] == second["capture_after_payload_sha256"]
    assert second["capture_before_receipt_sha256"] == second["capture_after_receipt_sha256"]
    assert second["data_update_status"] == "EXACT_ARTIFACT_REUSED"
    assert len(invocations) == 2


def test_closed_and_uncovered_calendar_dates_never_invoke_the_capture_cli(tmp_path: Path):
    invocations = []
    registry = FixedExecutorRegistry(data_root=tmp_path / "owned-data", repo_root=ROOT)

    def should_not_run(*args, **kwargs):
        invocations.append((args, kwargs))
        raise AssertionError("calendar gate invoked the US producer")

    registry._run = should_not_run
    holiday = DispatchRequest(
        scheduled_date="20260907",
        business_date="20260907",
        target_date="20260907",
        slot="2100",
        mode=DispatchMode.LIVE,
    )
    closed = registry._us_market_digest(holiday)
    assert closed["status"] == "SUCCEEDED"
    assert closed["capture_status"] == "CLOSED"
    assert closed["market_day_reason"] == "CLOSED_HOLIDAY"

    uncovered = DispatchRequest(
        scheduled_date="20270104",
        business_date="20270104",
        target_date="20270104",
        slot="2200",
        mode=DispatchMode.LIVE,
    )
    with pytest.raises(WorkloadExecutionError) as error:
        registry._us_market_digest(uncovered)
    assert error.value.result["market_day_status"] == "CANNOT_CONFIRM"
    assert error.value.result["market_day_reason"] == "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE"
    assert invocations == []


def test_cli_without_exact_provenance_keeps_existing_artifact_unconfirmed(
    tmp_path: Path,
):
    import json

    from infrastructure.data_store import _sha256
    from infrastructure.research_peripheral_store import ResearchPeripheralStore

    data_root = tmp_path / "owned-data"
    payload = us_market_digest.build_us_market_phase_payload(
        SESSION,
        capture_phase="PRE_OPEN",
        fetched_at=CAPTURED_AT,
        fetch_rss=lambda *_args: b"<rss><channel></channel></rss>",
    )
    store = ResearchPeripheralStore(data_root)
    store.publish(payload)
    payload_sha = _sha256(payload)
    summary = {
        "status": payload["status"],
        "trade_date": SESSION,
        "source": "external_finance",
        "payload_path": store._relative(SESSION, "external_finance"),
        "payload_sha256": payload_sha,
        "capture_origin": payload["capture_origin"],
        "original_time_capture": payload["original_time_capture"],
    }
    registry = FixedExecutorRegistry(data_root=data_root, repo_root=ROOT)
    registry._run = lambda *_args, **_kwargs: {
        "status": "SUCCEEDED",
        "exit_code": 0,
        "stdout": json.dumps(summary),
        "stderr": "",
    }
    request = DispatchRequest(
        scheduled_date=SESSION,
        business_date=SESSION,
        target_date=SESSION,
        slot="2100",
        mode=DispatchMode.LIVE,
    )

    result = registry._us_market_digest(request)

    assert result["capture_artifact_verified"] is True
    assert result["capture_performed"] is None
    assert result["new_capture_verified"] is False
    assert result["capture_reused"] is None
    assert result["data_update_status"] == "EXACT_ARTIFACT_VERIFIED_UPDATE_UNCONFIRMED"
    assert result["capture_before_payload_sha256"] == result["capture_after_payload_sha256"]


def test_verified_post_close_replacement_records_before_and_after_artifact_sha(
    tmp_path: Path, monkeypatch
):
    from infrastructure.data_store import _sha256
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    from ops.materialize_research_peripherals import build_external_finance_payload

    data_root = tmp_path / "owned-data"
    rss = lambda *_args: b"<rss><channel></channel></rss>"
    quotes = {
        symbol: {
            "last": 101.0,
            "previous_close": 100.0,
            "change_pct": 1.0,
            "session_date": SESSION,
            "session_time": "16:00:00",
        }
        for group in us_market_digest.GLOBAL_INDUSTRY_PROXY_MAP
        for symbol in group["proxy_symbols"]
    }
    legacy = build_external_finance_payload(
        SESSION,
        fetched_at="2026-09-24T12:59:30Z",
        fetch_rss=rss,
    )
    # This is an isolated, valid source artifact without a prior capture
    # identity; the real US owner must replace it with a close capture.
    legacy["cannot_confirm"] = []
    legacy["status"] = "READY"
    legacy["raw_item_count"] = 1
    legacy["item_count"] = 1
    legacy["details"] = [{
        "title": "synthetic fixture only",
        "recommendation_status": "RESEARCH_ONLY",
    }]
    store = ResearchPeripheralStore(data_root)
    store.publish(legacy)
    before_sha = _sha256(legacy)
    real_materialize = us_market_digest.materialize_us_market_phase

    def post_close_materialize(**kwargs):
        return real_materialize(
            **kwargs,
            fetched_at="2026-09-24T20:15:30Z",
            fetch_rss=rss,
            fetch_quotes=lambda *_args: quotes,
        )

    monkeypatch.setattr(us_market_digest, "materialize_us_market_phase", post_close_materialize)

    def process(command, *, cwd, timeout_seconds, env):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = us_market_digest.main(command[3:])
        return subprocess.CompletedProcess(
            command, returncode, stdout.getvalue(), stderr.getvalue()
        )

    registry = FixedExecutorRegistry(data_root=data_root, repo_root=ROOT, runner=process)
    request = DispatchRequest(
        scheduled_date="20260925",
        business_date="20260925",
        target_date="20260925",
        slot="0415",
        mode=DispatchMode.LIVE,
    )
    result = registry._us_market_digest(request)
    after = ResearchPeripheralStore(data_root).read_exact(SESSION, "external_finance")

    assert result["status"] == "SUCCEEDED", result
    assert result["capture_reused"] is False
    assert result["capture_replaced"] is True
    assert result["capture_performed"] is True
    assert result["new_capture_verified"] is True
    assert result["capture_before_payload_sha256"] == before_sha
    assert result["capture_after_payload_sha256"] == result["payload_sha256"]
    assert result["capture_after_payload_sha256"] != before_sha
    assert result["capture_before_receipt_sha256"] != result["capture_after_receipt_sha256"]
    assert result["capture_phase"] == "POST_CLOSE"
    assert result["capture_captured_at"] == "2026-09-24T20:15:30Z"
    assert result["receipt_verified"] is True
    assert after is not None
