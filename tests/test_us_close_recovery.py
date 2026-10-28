"""Regression for observed mixed-second close quotes and late API contract drift."""
from copy import deepcopy
from datetime import datetime

import pytest

from apps.api.v35_api import research_lane_router as lane
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, build_us_market_phase_payload
from ops._us_market_digest_parts.close_validation import normalize_close_snapshot


def capture():
    quotes = {symbol: {"last": 101, "previous_close": 100, "session_date": "20261014", "session_time": "16:00:01"}
              for row in GLOBAL_INDUSTRY_PROXY_MAP for symbol in row["proxy_symbols"]}
    quotes["NVDA"]["session_time"] = "16:04:36"
    return build_us_market_phase_payload("20261015", us_session_date="20261014", capture_phase="POST_CLOSE",
        fetched_at="2026-10-15T06:09:12Z", now="2026-10-15T06:09:12Z", allow_late_post_close=True,
        fetch_rss=lambda *a: b"<rss><channel></channel></rss>", fetch_quotes=lambda *a: quotes)


def test_mixed_seconds_are_regular_close_observations_and_late_api_agrees(tmp_path):
    payload = capture()
    snapshot = payload["market_snapshot"]
    assert snapshot["status"] == "READY"
    assert snapshot["provider_session_times"] == ["16:00:01", "16:04:36"]
    ResearchPeripheralStore(tmp_path).publish(payload)
    projection = lane._project_global_industries(store=ResearchPeripheralStore(tmp_path), research_date="20261015")
    result = lane._with_us_market_freshness(projection, observed=datetime.fromisoformat("2026-10-15T14:25:00Z"))
    assert result["display_status"] == "READY", result
    assert result["freshness"]["latest_exchange_session"] == "20261014"
    assert result["captured_at"] == "2026-10-15T06:09:12Z"


@pytest.mark.parametrize("field,value,reason", [
    ("session_time", "15:59:59", "QUOTE_OUTSIDE_COMPLETED_REGULAR_SESSION"),
    ("session_time", "25:00:00", "QUOTE_REGULAR_CLOSE_UNCONFIRMED"),
    ("session_time", "", "QUOTE_REGULAR_CLOSE_UNCONFIRMED"),
    ("session_date", "20261013", "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"),
])
def test_close_quality_is_not_upgraded_for_invalid_observation(field, value, reason):
    snapshot = deepcopy(capture()["market_snapshot"])
    snapshot["quotes"][0][field] = value
    result = normalize_close_snapshot(snapshot)
    assert result["status"] == "CANNOT_CONFIRM"
    assert reason in result["cannot_confirm"]


def test_quote_after_actual_capture_is_rejected():
    snapshot = capture()["market_snapshot"]
    snapshot["captured_at"] = "2026-10-14T20:02:00Z"
    assert normalize_close_snapshot(snapshot)["status"] == "CANNOT_CONFIRM"


def test_other_quality_failures_and_raw_quotes_are_retained():
    snapshot = capture()["market_snapshot"]
    snapshot["cannot_confirm"] = ["QUOTE_SESSION_TIME_MIXED", "QUOTE_SYMBOL_MISSING:FAKE"]
    snapshot["status"] = "CANNOT_CONFIRM"
    result = normalize_close_snapshot(snapshot)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["QUOTE_SYMBOL_MISSING:FAKE"]
    assert result["quotes"] == snapshot["quotes"]
    assert result["source_response_sha256"] == snapshot["source_response_sha256"]
