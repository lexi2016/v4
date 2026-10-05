from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from infrastructure.http_transport import FetchResult
from infrastructure.data_store import _sha256 as payload_sha256
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from ops.us_market_digest import (
    GLOBAL_INDUSTRY_PROXY_MAP,
    _deterministic_capture_id,
    build_us_market_phase_payload,
    materialize_us_market_phase,
)


NY = ZoneInfo("America/New_York")
LEGACY_PAYLOAD = Path(__file__).parent / "fixtures" / "us_external_finance_20261001.json"
LEGACY_RECEIPT = Path(__file__).parent / "fixtures" / "us_external_finance_20261001_legacy_receipt.json"
LEGACY_PAYLOAD_RELATIVE = "research/peripherals/20261001/external_finance.json"
LEGACY_RECEIPT_RELATIVE = "receipts/research/peripherals/20261001/external_finance.json"


def _seed_original_mixed_time_baseline(store: ResearchPeripheralStore) -> dict:
    payload_bytes = LEGACY_PAYLOAD.read_bytes()
    receipt_bytes = LEGACY_RECEIPT.read_bytes()
    root = store.root
    payload_path = root / LEGACY_PAYLOAD_RELATIVE
    receipt_path = root / LEGACY_RECEIPT_RELATIVE
    manifest_path = root / "research/peripherals/manifest.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(payload_bytes)
    receipt_path.write_bytes(receipt_bytes)
    payload = json.loads(payload_bytes)
    manifest_path.write_text(
        json.dumps({LEGACY_PAYLOAD_RELATIVE: payload_sha256(payload)}, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _rss_fetch(title: str, calls: list[str]):
    def fetch(url: str, _timeout: int):
        calls.append(url)
        key = sha256(url.encode("utf-8")).hexdigest()[:12]
        body = (
            "<rss><channel><item>"
            f"<title>US semiconductor quarterly earnings update {title} {key}</title>"
            f"<link>https://example.test/us-recovery/{key}</link>"
            "<pubDate>Fri, 02 Oct 2026 07:00:00 GMT</pubDate>"
            '<source url="https://www.reuters.com">Reuters</source>'
            "</item></channel></rss>"
        ).encode("utf-8")
        return FetchResult(
            body,
            {
                "elapsed_ms": 12,
                "http_status": 200,
                "error": None,
                "proxy_used": True,
                "fallback_used": False,
            },
        )

    return fetch


def _quote_fetch(session_date: str, calls: list[str], *, mixed_times: bool = False):
    def fetch(url: str, _timeout: int):
        calls.append(url)
        symbols = list(
            dict.fromkeys(
                symbol
                for mapping in GLOBAL_INDUSTRY_PROXY_MAP
                for symbol in mapping["proxy_symbols"]
            )
        )
        records = []
        for index, symbol in enumerate(symbols):
            fields = [""] * 31
            fields[1:5] = [symbol, symbol, "110", "100"]
            provider_time = "160000" if not mixed_times or index < len(symbols) // 2 else "160400"
            fields[30] = f"{session_date}{provider_time}"
            records.append(f'v_us{symbol}="{"~".join(fields)}";')
        body = "".join(records).encode("utf-8")
        return FetchResult(
            body,
            {
                "elapsed_ms": 8,
                "http_status": 200,
                "error": None,
                "proxy_used": True,
                "fallback_used": False,
            },
        )

    return fetch


def test_late_rss_recovery_accepts_only_latest_completed_session_before_network():
    calls: list[str] = []
    quotes: list[str] = []
    now = datetime(2026, 10, 2, 3, 15, tzinfo=NY)

    with pytest.raises(ValueError, match="US_LATE_POST_CLOSE_NOT_LATEST_COMPLETED_SESSION"):
        build_us_market_phase_payload(
            "20260930",
            us_session_date="20260930",
            capture_phase="POST_CLOSE",
            allow_late_post_close=True,
            rss_only_recovery=True,
            now=now,
            fetch_rss=_rss_fetch("美股公司季度业绩观察", calls),
            fetch_quotes=_quote_fetch("20260930", quotes),
        )

    assert calls == []
    assert quotes == []


def test_rss_only_recovery_requires_original_33_quote_24_row_snapshot_before_network(tmp_path):
    calls: list[str] = []
    quotes: list[str] = []
    with pytest.raises(ValueError, match="US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_ARTIFACT"):
        materialize_us_market_phase(
            data_root=tmp_path / "missing-baseline",
            trade_date="20261001",
            us_session_date="20261001",
            capture_phase="POST_CLOSE",
            allow_late_post_close=True,
            rss_only_recovery=True,
            now=datetime(2026, 10, 2, 3, 15, tzinfo=NY),
            fetch_rss=_rss_fetch("US recovery baseline required", calls),
            fetch_quotes=_quote_fetch("20261001", quotes),
        )
    assert calls == []
    assert quotes == []


def test_late_rss_recovery_uses_actual_now_and_preserves_prior_quote_snapshot(tmp_path):
    store = ResearchPeripheralStore(tmp_path / "data")
    original = _seed_original_mixed_time_baseline(store)
    assert original["status"] == "CANNOT_CONFIRM"
    assert original["market_snapshot_status"] == "CANNOT_CONFIRM"
    prior_snapshot = original["market_snapshot"]
    prior_payload_sha256 = payload_sha256(original)
    assert len(prior_snapshot["quotes"]) == 33
    assert len(prior_snapshot["rows"]) == 24
    assert "QUOTE_SESSION_TIME_MIXED" in prior_snapshot["cannot_confirm"]
    natural_capture = original["us_session_captures"][0]
    natural_capture_id = natural_capture["capture_id"]
    assert natural_capture_id == _deterministic_capture_id("20261001", "POST_CLOSE")

    recovery_now = datetime(2026, 10, 2, 3, 15, tzinfo=NY)
    recovery_rss_calls: list[str] = []
    unexpected_quote_calls: list[str] = []
    recovered = materialize_us_market_phase(
        data_root=tmp_path / "data",
        trade_date="20261001",
        us_session_date="20261001",
        capture_phase="POST_CLOSE",
        allow_late_post_close=True,
        rss_only_recovery=True,
        now=recovery_now,
        fetch_rss=_rss_fetch("美股公司季度业绩观察晚间补采", recovery_rss_calls),
        fetch_quotes=_quote_fetch("20261001", unexpected_quote_calls),
    )

    latest = store.read_exact("20261001", "external_finance")
    assert latest is not None
    assert recovered["capture_id"] != natural_capture_id
    late_rows = [row for row in latest["us_session_captures"] if row.get("late") is True]
    assert len(late_rows) == 1
    late_capture = late_rows[0]
    assert late_capture["rss_status"] == "READY"
    assert late_capture["rss_item_count"] > 0
    assert late_capture["quote_capture_status"] == "NOT_ATTEMPTED"
    assert late_capture["quote_capture_reason"] == "RSS_ONLY_RECOVERY"
    assert late_capture["capture_origin"] == "MANUAL_RECOVERY"
    assert late_capture["original_time_capture"] is False
    assert late_capture["reason"] == "MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION"
    assert late_capture["capture_id"] != natural_capture_id
    assert late_capture["captured_at"] == "2026-10-02T07:15:00Z"
    assert latest["market_snapshot"] == prior_snapshot
    assert payload_sha256(latest["market_snapshot"]) == payload_sha256(prior_snapshot)
    assert latest["market_snapshot"]["captured_at"] == prior_snapshot["captured_at"]
    assert latest["market_snapshot"]["source_response_sha256"] == prior_snapshot["source_response_sha256"]
    assert len(latest["market_snapshot"]["quotes"]) == 33
    assert len(latest["market_snapshot"]["rows"]) == 24
    assert latest["market_snapshot_status"] == "CANNOT_CONFIRM"
    assert latest["status"] == "CANNOT_CONFIRM"
    assert recovered["previous_payload_path"]
    previous_payload = store._read(recovered["previous_payload_path"])
    assert previous_payload == original
    assert payload_sha256(previous_payload) == prior_payload_sha256
    current_receipt = store._read(recovered["receipt_path"])
    assert current_receipt["market_snapshot_sha256"] == payload_sha256(prior_snapshot)
    assert current_receipt["market_snapshot_captured_at"] == prior_snapshot["captured_at"]
    assert current_receipt["market_snapshot_source_response_sha256"] == prior_snapshot["source_response_sha256"]
    assert current_receipt["captured_at"] == late_capture["captured_at"]
    assert current_receipt["capture_origin"] == "MANUAL_RECOVERY"
    assert current_receipt["original_time_capture"] is False
    assert current_receipt["quote_capture_status"] == "NOT_ATTEMPTED"
    assert recovery_rss_calls and len(recovery_rss_calls) == 5
    assert unexpected_quote_calls == []

    # The same stable instant is an idempotent retry and issues no second RSS request.
    repeated = materialize_us_market_phase(
        data_root=tmp_path / "data",
        trade_date="20261001",
        us_session_date="20261001",
        capture_phase="POST_CLOSE",
        allow_late_post_close=True,
        rss_only_recovery=True,
        now=recovery_now,
        fetch_rss=_rss_fetch("should-not-run", recovery_rss_calls),
        fetch_quotes=_quote_fetch("20261001", unexpected_quote_calls),
    )
    assert repeated["reused"] is True
    assert len(recovery_rss_calls) == 5
    assert unexpected_quote_calls == []


def test_late_rss_only_is_explicit_and_keeps_quote_snapshot_cannot_confirm(tmp_path):
    calls: list[str] = []
    quotes: list[str] = []
    now = datetime(2026, 10, 2, 3, 15, tzinfo=NY)
    payload = build_us_market_phase_payload(
        "20261001",
        us_session_date="20261001",
        capture_phase="POST_CLOSE",
        allow_late_post_close=True,
        rss_only_recovery=True,
        now=now,
        fetch_rss=_rss_fetch("美股公司季度业绩观察", calls),
        fetch_quotes=_quote_fetch("20261001", quotes),
    )
    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["market_snapshot_status"] == "CANNOT_CONFIRM"
    assert payload["us_session_captures"][0]["rss_status"] == "READY"
    assert payload["us_session_captures"][0]["quote_capture_status"] == "NOT_ATTEMPTED"
    assert payload["us_session_captures"][0]["capture_origin"] == "MANUAL_RECOVERY"
    assert payload["us_session_captures"][0]["original_time_capture"] is False
    assert payload["us_session_captures"][0]["reason"] == "MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION"
    assert calls and len(calls) == 5
    assert quotes == []
