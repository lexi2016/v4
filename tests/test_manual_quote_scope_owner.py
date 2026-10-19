import json
from pathlib import Path

import pytest

from ops.us_market_digest import (
    build_manual_quote_scope_canary,
    materialize_us_manual_quote_scope_backfill,
)
from v4.manager_workbench.inputs.us_universe import build_us_universe_contract
from v4.manager_workbench.inputs import source_bindings


ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / "docs/handoffs/full_us_hk_mapping_consumption_20261019/local_only/manual_quote_scope.json"
CAPTURED_AT = "2026-10-19T15:00:00+08:00"


def _scope():
    return json.loads(SCOPE_PATH.read_text(encoding="utf-8"))


def _quotes(symbols, *, missing=(), before_close=()):
    missing, before_close = set(missing), set(before_close)
    return {
        f"v_us{symbol}": {
            "last": 101,
            "previous_close": 100,
            "session_date": "20261016",
            "session_time": "15:59:59" if symbol in before_close else "16:00:01",
        }
        for symbol in symbols if symbol not in missing
    }


def test_manual_quote_canary_is_fixed_scope_and_isolates_bad_symbols():
    scope = _scope()
    canary_symbols = sorted(set(build_us_universe_contract()["symbols"])
        | {"AAGIY", "MDLZ", "SHEL", "KIE", "XLU"})
    response = _quotes(canary_symbols, missing={"AAGIY"}, before_close={"MDLZ"})
    requested_urls = []

    result = build_manual_quote_scope_canary(session_date="20261016", scope=scope,
        now=CAPTURED_AT, fetch_quotes=lambda url, timeout: (requested_urls.append(url) or response))

    assert result["capture_mode"] == "MANUAL_QUOTE_SCOPE_CANARY"
    assert result["manual_quote_scope"]["scope_mode"] == "CANARY"
    assert result["requested_symbol_count"] == len(canary_symbols)
    assert result["status"] == "PARTIAL"
    assert result["available_symbol_count"] == len(canary_symbols) - 2
    assert result["quote_failures"] == {
        "AAGIY": "QUOTE_SYMBOL_MISSING",
        "MDLZ": "QUOTE_PROVIDER_TIMESTAMP_BEFORE_OFFICIAL_CLOSE",
    }
    assert len(requested_urls) == 1
    assert "usAAGIY" in requested_urls[0] and "usXLU" in requested_urls[0]
    assert result["RESEARCH_ONLY"] is True
    assert result["production_allowed"] is False


def test_manual_quote_owner_rejects_nonlatest_session_before_fetch():
    calls = []
    with pytest.raises(ValueError, match="US_MANUAL_QUOTE_SESSION_NOT_LATEST_COMPLETED"):
        build_manual_quote_scope_canary(session_date="20261015", scope=_scope(),
            now=CAPTURED_AT, fetch_quotes=lambda *_: calls.append(True))
    assert calls == []


def test_manual_backfill_publishes_once_and_refuses_collision_without_refetch(tmp_path):
    scope = _scope()
    symbols = scope["symbols"]
    response = _quotes(symbols)
    calls = []

    first = materialize_us_manual_quote_scope_backfill(data_root=tmp_path,
        trade_date="20261019", session_date="20261016", scope=scope,
        now=CAPTURED_AT,
        fetch_quotes=lambda *_: (calls.append(True) or response))

    assert first["payload"]["capture_origin"] == "HISTORICAL_BACKFILL"
    assert first["payload"]["original_time_capture"] is False
    assert first["payload"]["capture_mode"] == "MANUAL_QUOTE_SCOPE_EXPANSION"
    assert first["payload"]["market_snapshot"]["status"] == "READY"
    assert first["payload"]["market_snapshot"]["available_symbol_count"] == 547
    payload_path = tmp_path / first["payload_path"]
    before = payload_path.read_bytes()
    with pytest.raises(ValueError, match="US_MANUAL_QUOTE_SCOPE_BACKFILL_PATH_ALREADY_EXISTS"):
        materialize_us_manual_quote_scope_backfill(data_root=tmp_path,
            trade_date="20261019", session_date="20261016", scope=scope,
            now=CAPTURED_AT,
            fetch_quotes=lambda *_: (calls.append(True) or response))
    assert payload_path.read_bytes() == before
    assert len(calls) == 1


def test_manual_quote_source_binding_pins_exact_artifact_and_isolates_coverage(tmp_path):
    scope = _scope()
    response = _quotes(scope["symbols"], missing={"MDLZ"})
    materialized = materialize_us_manual_quote_scope_backfill(data_root=tmp_path,
        trade_date="20261019", session_date="20261016", scope=scope,
        now=CAPTURED_AT, fetch_quotes=lambda *_: response)
    manifest, manifest_sha = source_bindings.read(tmp_path, "research/peripherals/manifest.json")
    _, receipt_sha = source_bindings.read(tmp_path, materialized["receipt_path"])

    base = set(build_us_universe_contract()["symbols"])
    catalog_symbols = (set(scope["symbols"]) - base - {"XLU", "KIE"}) | set(sorted(base)[:20])
    assert len(catalog_symbols) == 517
    full_overlay = {
        "state": "READY",
        "catalog_file_sha256": "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671",
        "relations": [{"source_record": {"asset_code": symbol}} for symbol in sorted(catalog_symbols)]
            + [{"source_record": {"asset_code": "CHU（历史）"}}],
    }

    binding = source_bindings._manual_quote_scope_binding(tmp_path, manifest, manifest_sha,
        "20261016", "2026-10-20T08:00:00+08:00", full_overlay, sorted(base))

    assert binding["state"] == "PARTIAL"
    assert binding["owner"] == "research_peripheral.external_finance.manual_quote_scope"
    assert binding["scope_sha256"] == scope["scope_sha256"]
    assert binding["payload_sha256"] == materialized["payload_sha256"]
    assert binding["receipt_sha256"] == receipt_sha
    assert binding["manifest_sha256"] == manifest_sha
    assert binding["available_symbol_count"] == 546
    assert binding["requested_symbol_count"] == 547
    assert binding["symbol_gaps"]["MDLZ"] == "QUOTE_SYMBOL_MISSING"
    assert len(binding["quotes"]) == 546
