from copy import deepcopy
import json
from pathlib import Path

import pytest

from v4.manager_workbench.inputs.us_mapping_close_scope import (
    OWNER, PROVENANCE, SCOPE_SHA, bind_scheduled_scope,
    build_scope_observations, configured_request_scope, digest,
)

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "docs/handoffs/us_mapping_auto_close_20261020/quote_scope.json"
SESSION = "20261019"
CAPTURED = "2026-10-19T20:15:04Z"
CUTOFF = "2026-10-20T04:16:00+08:00"


def request():
    return json.loads(CONFIG.read_text())


def record(symbol, **updates):
    return {"symbol": symbol, "last": 101, "previous_close": 100, "pct_change": 1,
            "session_date": SESSION, "session_time": "16:00:02", **updates}


def prepared(records=None, *, captured=CAPTURED):
    values = records or {s: record(s) for s in ["WMT", "KO", "PG"]}
    scope = build_scope_observations(request(), values, {}, source_session=SESSION,
                                     captured_at=captured, source_response_sha256="a" * 64)
    snapshot = {"scheduled_quote_scope": scope, "source_response_sha256": "a" * 64,
                "capture_session_date": SESSION, "capture_phase": "POST_CLOSE", "captured_at": captured}
    payload = {"us_session_captures": [{"us_session_date": SESSION, "capture_phase": "POST_CLOSE",
                                       "captured_at": captured, "capture_origin": "ORIGINAL_TIME_CAPTURE",
                                       "original_time_capture": True}]}
    return snapshot, payload


def bind(snapshot, payload, **changes):
    kwargs = dict(source_session=SESSION, cutoff=CUTOFF,
                  payload_relative="research/peripherals/20261020/external_finance.json",
                  payload_sha256="b" * 64,
                  receipt_relative="receipts/research/peripherals/20261020/external_finance.json",
                  receipt_sha256="c" * 64, manifest_sha256="d" * 64)
    kwargs.update(changes)
    return bind_scheduled_scope(snapshot, payload, **kwargs)


def reseal(snapshot):
    scope = snapshot["scheduled_quote_scope"]
    scope["record_sha256"] = digest({k: v for k, v in scope.items() if k != "record_sha256"})


def test_frozen_scope_uses_same_547_identity_and_config_is_opt_in(monkeypatch):
    monkeypatch.delenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", raising=False)
    assert configured_request_scope() is None
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    configured = configured_request_scope()
    assert len(configured["symbols"]) == 547
    assert configured["scope_sha256"] == SCOPE_SHA
    assert {s for s in ["WMT", "KO", "PG"]} <= set(configured["symbols"])
    changed = request()
    changed["symbols"][0] = "ARBITRARY"
    with pytest.raises(ValueError, match="FROZEN_IDENTITY"):
        build_scope_observations(changed, {}, {}, source_session=SESSION,
                                 captured_at=CAPTURED, source_response_sha256="a" * 64)


def test_scheduled_identity_and_partial_siblings_are_retained():
    snapshot, payload = prepared()
    bound = bind(snapshot, payload)
    assert bound["owner"] == OWNER
    assert bound["capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert bound["state"] == "PARTIAL"
    assert bound["available_symbol_count"] == 3
    assert bound["requested_symbol_count"] == 547
    assert set(bound["quotes"]) == {"WMT", "KO", "PG"}
    assert bound["payload_sha256"] == "b" * 64
    assert bound["source_response_sha256"] == "a" * 64


@pytest.mark.parametrize("changes", [
    {"symbol": "WMT"}, {"session_date": "20261016"}, {"session_time": "15:59:59"},
    {"session_time": "16:16:00"}, {"session_time": "bad"}, {"last": -1},
    {"previous_close": 0}, {"previous_close": None}, {"change_pct": 9},
    {"change_pct": True}, {"last": "Infinity"}, {"previous_close": "NaN"},
])
def test_bad_quote_is_quarantined_without_dropping_valid_siblings(changes):
    snapshot, payload = prepared()
    quote = next(q for q in snapshot["scheduled_quote_scope"]["quotes"] if q["symbol"] == "KO")
    quote.update(changes)
    reseal(snapshot)
    bound = bind(snapshot, payload)
    assert bound["state"] == "PARTIAL"
    assert "KO" not in bound["quotes"]
    assert "PG" in bound["quotes"]
    # A KO record relabelled WMT also invalidates the duplicate WMT identity.
    if changes.get("symbol") != "WMT":
        assert "WMT" in bound["quotes"]


@pytest.mark.parametrize("failure", ["session", "future", "digest", "source_sha", "owner",
                                      "provenance", "receipt_sha", "late", "historical"])
def test_wrong_identity_or_non_natural_capture_cannot_fallback(failure):
    snapshot, payload = prepared()
    changes = {}
    value = snapshot["scheduled_quote_scope"]
    if failure == "session":
        changes["source_session"] = "20261016"
    elif failure == "future":
        changes["cutoff"] = "2026-10-19T20:14:59Z"
    elif failure == "digest":
        value["record_sha256"] = "e" * 64
    elif failure == "source_sha":
        snapshot["source_response_sha256"] = "e" * 64
    elif failure == "owner":
        value["owner"] = "manual-owner"
        reseal(snapshot)
    elif failure == "provenance":
        value["catalog_sha256"] = "e" * 64
        reseal(snapshot)
    elif failure == "receipt_sha":
        changes["receipt_sha256"] = "unknown"
    elif failure == "late":
        payload["us_session_captures"][0]["late"] = True
    else:
        payload["us_session_captures"][0]["capture_origin"] = "HISTORICAL_BACKFILL"
    assert bind(snapshot, payload, **changes)["state"] == "CANNOT_CONFIRM"
    assert bind({}, payload) is None


def test_provider_inner_ticker_disagreement_is_not_a_valid_supplement():
    scope = build_scope_observations(request(), {s: record(s) for s in ["WMT", "PG"]}, {},
                                     source_session=SESSION, captured_at=CAPTURED,
                                     source_response_sha256="a" * 64,
                                     raw_response={"WMT": {"symbol": "KO"}, "PG": {"symbol": "PG"}})
    assert [q["symbol"] for q in scope["quotes"]] == ["PG"]
    assert scope["quote_failures"]["WMT"] == "QUOTE_SYMBOL_MISMATCH"


def test_calendar_handles_other_sessions_and_early_close():
    values = {"WMT": record("WMT", session_date="20261127", session_time="13:00:01")}
    scope = build_scope_observations(request(), values, {}, source_session="20261127",
                                     captured_at="2026-11-27T18:15:00Z", source_response_sha256="a" * 64)
    assert scope["available_symbol_count"] == 1
    assert scope["us_session_date"] == "20261127"


def controlled_late():
    from ops.us_market_digest import build_capture_metadata
    captured = "2026-10-19T21:15:04Z"
    snapshot, payload = prepared(captured=captured)
    capture = build_capture_metadata(SESSION, "POST_CLOSE", captured_at=captured,
        capture_id="existing-automatic-close-retry", run_id="existing-automatic-close-retry",
        allow_late_post_close=True, now=captured)
    payload["us_session_captures"] = [capture]
    return snapshot, payload


def test_legal_automatic_late_uses_actual_outer_validator_and_keeps_timing():
    from infrastructure.research_peripheral_store import _validate_us_session_captures
    snapshot, payload = controlled_late()
    capture = payload["us_session_captures"][0]
    assert _validate_us_session_captures([capture]) == [capture]
    bound = bind(snapshot, payload, cutoff="2026-10-20T05:16:00+08:00")
    assert bound["state"] == "PARTIAL"
    assert set(bound["quotes"]) == {"WMT", "KO", "PG"}
    assert bound["late"] is True
    assert bound["capture_timing"] == bound["capture_mode"] == "CONTROLLED_LATE_POST_CLOSE"
    assert bound["capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert bound["available_at"] == capture["captured_at"]
    assert bound["capture_metadata"] == capture


@pytest.mark.parametrize("failure", ["mode", "window", "outside_window", "missing", "manual", "flag_type"])
def test_forged_or_incomplete_late_does_not_bypass_owner_contract(failure):
    snapshot, payload = controlled_late()
    capture = payload["us_session_captures"][0]
    if failure == "mode":
        capture["capture_mode"] = "TRUSTED_LATE"
    elif failure == "window":
        capture["allowed_recovery_window_end"] = "2026-10-21T16:15:00-04:00"
    elif failure == "outside_window":
        capture["captured_at"] = snapshot["captured_at"] = "2026-10-21T21:15:04Z"
        snapshot["scheduled_quote_scope"]["captured_at"] = snapshot["captured_at"]
        reseal(snapshot)
    elif failure == "missing":
        capture.pop("natural_capture_window_start")
    elif failure == "manual":
        capture.update(capture_origin="MANUAL_RECOVERY", original_time_capture=False)
    else:
        capture["late"] = "true"
    assert bind(snapshot, payload, cutoff="2026-10-22T05:16:00+08:00")["state"] == "CANNOT_CONFIRM"
