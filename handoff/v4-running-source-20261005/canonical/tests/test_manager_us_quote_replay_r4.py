from copy import deepcopy

from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, build_us_market_snapshot, _merge_market_snapshots
from v4.manager_research.us_market_bridge import project_us_market


def _quotes(session_date="20260930"):
    symbols = sorted({symbol for row in GLOBAL_INDUSTRY_PROXY_MAP for symbol in row["proxy_symbols"]})
    times = ["16:00:01", "16:00:22", "16:00:36", "16:00:37", "16:00:40"]
    return {
        symbol: {
            "last": 101.0,
            "previous_close": 100.0,
            "change_pct": 1.0,
            "session_date": session_date,
            "session_time": times[index % len(times)],
        }
        for index, symbol in enumerate(symbols)
    }


def _false_partial_snapshot():
    snapshot = build_us_market_snapshot(
        "20260930", capture_phase="POST_CLOSE", captured_at="2026-10-01T04:15:00+08:00",
        fetch_quotes=lambda *_args, **_kwargs: _quotes(),
    )
    # Recreate the exact saved defect while keeping its normalized quote rows.
    snapshot["status"] = "PARTIAL"
    snapshot["cannot_confirm"] = ["MARKET_SNAPSHOT_INCOMPLETE", "QUOTE_SESSION_TIME_MIXED"]
    for row in snapshot["rows"]:
        row["cannot_confirm"] = ["QUOTE_SESSION_TIME_MIXED"]
        if len(row["quote_session_times"]) > 1:
            row["status"] = "PARTIAL"
    return snapshot


def test_same_session_seconds_are_diagnostic_and_merge_recheck_clears_only_time_dispersion():
    snapshot = build_us_market_snapshot(
        "20260930", capture_phase="POST_CLOSE", captured_at="2026-10-01T04:15:00+08:00",
        fetch_quotes=lambda *_args, **_kwargs: _quotes(),
    )
    assert snapshot["status"] == "READY"
    assert len(snapshot["provider_session_dates"]) == 1
    assert len(snapshot["provider_session_times"]) > 1
    assert "QUOTE_SESSION_TIME_MIXED" not in snapshot["cannot_confirm"]
    cpo = next(row for row in snapshot["rows"] if row["label"] == "CPO")
    assert cpo["status"] == "READY"
    assert len(cpo["quote_session_times"]) > 1
    assert "QUOTE_SESSION_TIME_MIXED" not in cpo["cannot_confirm"]

    merged = _merge_market_snapshots(snapshot, snapshot)
    assert merged["status"] == "READY"
    assert "QUOTE_SESSION_TIME_MIXED" not in merged["cannot_confirm"]


def test_cross_session_quote_date_stays_blocked():
    quotes = _quotes()
    quotes[sorted(quotes)[0]]["session_date"] = "20260929"
    snapshot = build_us_market_snapshot(
        "20260930", capture_phase="POST_CLOSE", captured_at="2026-10-01T04:15:00+08:00",
        fetch_quotes=lambda *_args, **_kwargs: quotes,
    )
    assert snapshot["status"] != "READY"
    assert "QUOTE_SESSION_DATE_MISMATCH_CAPTURE" in snapshot["cannot_confirm"]


class _Reader:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def read_exact_session(self, session_date):
        self.calls.append(session_date)
        return deepcopy(self.payload), {
            "status": "VERIFIED", "payload_sha256": "a" * 64,
            "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64,
        }


def test_exact_verified_stored_snapshot_is_replayed_without_mutating_owner_or_hash():
    snapshot = _false_partial_snapshot()
    payload = {
        "schema_version": "v3_5.research_peripheral.v1",
        "trade_date": "20260930", "status": "CANNOT_CONFIRM",
        "market_snapshot": snapshot,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    before = deepcopy(payload)
    reader = _Reader(payload)
    out = project_us_market(reader, "20261002", {"research_cutoff": "2026-10-01T08:46:37+08:00"})

    assert reader.calls == ["20260930"]
    assert out["status"] == "READY"
    assert out["mapping_eligible"] is True
    assert out["stored_snapshot_status"] == "PARTIAL"
    assert out["stored_payload_status"] == "CANNOT_CONFIRM"
    assert out["source_response_sha256"] == before["market_snapshot"]["source_response_sha256"]
    replay = out["recheck_evidence"]
    assert replay["status"] == "RECHECKED_READY"
    assert replay["storage_mutated"] is False
    assert replay["replay_input_sha256"] != replay["stored_source_response_sha256"]
    assert out["raw_individual_up"] and out["raw_industry_up"]
    assert payload == before


def test_recheck_does_not_clear_any_unrelated_saved_failure():
    snapshot = _false_partial_snapshot()
    snapshot["cannot_confirm"].append("QUOTE_PCT_CHANGE_MISMATCH")
    payload = {"trade_date": "20260930", "status": "CANNOT_CONFIRM", "market_snapshot": snapshot}
    out = project_us_market(_Reader(payload), "20261002", {"research_cutoff": "2026-10-01T08:46:37+08:00"})
    assert out["status"] == "PARTIAL"
    assert out["recheck_evidence"] is None
    assert out["stored_snapshot_cannot_confirm"] == [
        "MARKET_SNAPSHOT_INCOMPLETE", "QUOTE_SESSION_TIME_MIXED", "QUOTE_PCT_CHANGE_MISMATCH"
    ]
