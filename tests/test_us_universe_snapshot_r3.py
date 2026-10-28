from copy import deepcopy

import pytest

from infrastructure.research_peripheral_store import _validate_market_snapshot
from ops.us_market_digest import build_us_market_snapshot
from v4.manager_workbench.inputs.us_universe import build_us_universe_contract


def _quotes(symbols):
    return {
        symbol: {
            "last": 101.0,
            "previous_close": 100.0,
            "session_date": "20261012",
            "session_time": "16:00:00",
        }
        for symbol in symbols
    }


def test_quote_owner_requests_48_but_keeps_24_proxy_rows_and_store_accepts():
    contract = build_us_universe_contract()
    requested = []
    snapshot = build_us_market_snapshot(
        "20261012",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-12T16:18:00-04:00",
        fetch_quotes=lambda url, _timeout: (requested.append(url) or _quotes(contract["symbols"])),
    )

    assert len(requested) == 1
    assert all(f"us{symbol}" in requested[0] for symbol in contract["symbols"])
    assert snapshot["requested_symbol_count"] == 48
    assert snapshot["available_symbol_count"] == 48
    assert len(snapshot["quotes"]) == 48
    assert len(snapshot["rows"]) == 24
    assert snapshot["universe_contract"] == contract
    assert snapshot["status"] == "READY"
    _validate_market_snapshot(snapshot)


def test_missing_internet_symbol_is_explicit_and_keeps_valid_quotes():
    contract = build_us_universe_contract()
    partial_quotes = _quotes(contract["symbols"])
    partial_quotes.pop("PDD")
    snapshot = build_us_market_snapshot(
        "20261012",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-12T16:18:00-04:00",
        fetch_quotes=lambda _url, _timeout: partial_quotes,
    )

    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["requested_symbol_count"] == 48
    assert snapshot["available_symbol_count"] == 47
    assert "QUOTE_SYMBOL_MISSING:PDD" in snapshot["cannot_confirm"]
    assert len(snapshot["rows"]) == 24
    _validate_market_snapshot(snapshot)


def test_legacy_snapshot_without_contract_remains_33_quote_compatible():
    contract = build_us_universe_contract()
    snapshot = build_us_market_snapshot(
        "20261012",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-12T16:18:00-04:00",
        fetch_quotes=lambda _url, _timeout: _quotes(contract["legacy_symbols"]),
    )
    legacy = deepcopy(snapshot)
    legacy.pop("universe_contract")
    legacy["requested_symbol_count"] = 33
    assert len(legacy["quotes"]) == 33
    _validate_market_snapshot(legacy)


def test_late_capture_recovery_window_matches_producer_and_publishes_exact_target_date(tmp_path, monkeypatch):
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    from ops.us_market_digest import build_us_market_phase_payload

    monkeypatch.delenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", raising=False)
    monkeypatch.delenv("V35_APP_ROOT", raising=False)

    contract = build_us_universe_contract()
    quotes = {
        symbol: {
            "last": 101.0,
            "previous_close": 100.0,
            "session_date": "20261013",
            "session_time": "16:00:00",
        }
        for symbol in contract["symbols"]
    }
    captured_at = "2026-10-14T07:52:00-04:00"
    payload = build_us_market_phase_payload(
        "20261014",
        capture_phase="POST_CLOSE",
        us_session_date="20261013",
        fetched_at=captured_at,
        capture_id="R5-LATE-20261014-POST-CLOSE",
        run_id="R5-LATE-20261014-POST-CLOSE",
        fetch_rss=lambda *_args, **_kwargs: b"<rss><channel></channel></rss>",
        fetch_quotes=lambda *_args, **_kwargs: quotes,
        allow_late_post_close=True,
        now=captured_at,
    )
    capture = next(
        row
        for row in payload["us_session_captures"]
        if row["capture_id"] == "R5-LATE-20261014-POST-CLOSE"
    )

    assert payload["trade_date"] == "20261014"
    assert capture["us_session_date"] == "20261013"
    assert capture["allowed_recovery_window_start"] == "2026-10-13T16:15:00-04:00"
    assert capture["allowed_recovery_window_end"] == "2026-10-14T16:15:00-04:00"
    assert payload["market_snapshot"]["capture_session_date"] == "20261013"
    assert payload["market_snapshot"]["requested_symbol_count"] == 48
    assert payload["market_snapshot"]["available_symbol_count"] == 48

    store = ResearchPeripheralStore(tmp_path / "valid")
    published = store.publish(payload)
    assert published["trade_date"] == "20261014"
    assert (tmp_path / "valid" / published["receipt_path"]).is_file()
    saved = store.read_exact("20261014", "external_finance")
    assert saved is not None
    assert saved["market_snapshot"]["capture_session_date"] == "20261013"
    assert saved["us_session_captures"][0]["allowed_recovery_window_end"] == "2026-10-14T16:15:00-04:00"

    wrong_window = deepcopy(payload)
    wrong_capture = next(
        row
        for row in wrong_window["us_session_captures"]
        if row["capture_id"] == "R5-LATE-20261014-POST-CLOSE"
    )
    wrong_capture["allowed_recovery_window_end"] = "2026-10-13T20:00:00-04:00"
    with pytest.raises(ValueError, match="late capture recovery window mismatch"):
        ResearchPeripheralStore(tmp_path / "invalid").publish(wrong_window)
