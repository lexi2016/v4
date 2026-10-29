from __future__ import annotations

import sys
import types
import importlib.util
import json
from pathlib import Path

import pytest

from apps.api.v4_api import a_share_panel_history as history


STATIC_ROOT = "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-20261029-r2-api/research-panel"
WORKTREE = Path(__file__).resolve().parents[1]
STATIC_BUILDER_PATH = WORKTREE / "ops/prepare_daily_numeric283_static.py"
STATIC_BUILDER_SPEC = importlib.util.spec_from_file_location("numeric283_static_builder_test", STATIC_BUILDER_PATH)
STATIC_BUILDER = importlib.util.module_from_spec(STATIC_BUILDER_SPEC)
STATIC_BUILDER_SPEC.loader.exec_module(STATIC_BUILDER)


def test_pinned_numeric283_scope_loads_exact_membership(monkeypatch):
    monkeypatch.setenv("V4_RESEARCH_PANEL_ROOT", STATIC_ROOT)
    symbols = history._numeric283_scope_symbols()
    assert len(symbols) == 283
    assert {"600025.SH", "300071.SZ", "920005.BJ"} <= symbols


def test_numeric283_scope_rejects_artifact_sha_drift(monkeypatch, tmp_path):
    monkeypatch.setenv("V4_RESEARCH_PANEL_ROOT", str(tmp_path))
    (tmp_path / "numeric283-candidates.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(history.Unconfirmed, match="NUMERIC283_SCOPE_ARTIFACT_SHA_CONFLICT"):
        history._numeric283_scope_symbols()


def test_numeric283_profile_fails_closed_for_wrong_date_and_out_of_scope_symbol(monkeypatch):
    monkeypatch.setenv("V4_RESEARCH_PANEL_ROOT", STATIC_ROOT)
    wrong_date = history.read_history(
        None, "600025.SH", "20260101", "20261027", history.NUMERIC283_CHART_PROFILE,
    )
    assert wrong_date["status"] == "CANNOT_CONFIRM"
    assert wrong_date["cannot_confirm"] == ["NUMERIC283_EXACT_20260101_20261028_RANGE_REQUIRED"]

    outside = history.read_history(
        None, "999999.SH", "20260101", "20261028", history.NUMERIC283_CHART_PROFILE,
    )
    assert outside["status"] == "CANNOT_CONFIRM"
    assert outside["cannot_confirm"] == ["NUMERIC283_SYMBOL_OUTSIDE_PINNED_SCOPE"]


def test_numeric283_finalizer_requires_pinned_generation_artifact_and_d28_row():
    response = {
        "status": "READY",
        "rows": [{"ts_code": "600025.SH", "trade_date": "20261028"}],
        "identity": {
            "generation_id": history.NUMERIC283_SOURCE_GENERATION,
            "artifact_sha256": history.NUMERIC283_SOURCE_ARTIFACT_SHA256,
            "asof_date": 20261028,
        },
    }
    accepted = history._numeric283_finalize(response, "600025.SH")
    assert accepted["status"] == "READY"
    assert accepted["signal_namespace"] == history.NUMERIC283_SIGNAL_NAMESPACE

    for key, value in (
        ("generation_id", "changed"),
        ("artifact_sha256", "0" * 64),
        ("asof_date", 20261027),
    ):
        changed = {**response, "identity": {**response["identity"], key: value}}
        rejected = history._numeric283_finalize(changed, "600025.SH")
        assert rejected["status"] == "CANNOT_CONFIRM"
        assert rejected["rows"] == []
        assert "NUMERIC283_SOURCE_BINDING_OR_D28_RANGE_CONFLICT" in rejected["cannot_confirm"]


def test_direct_overlay_is_skipped_only_for_numeric283_chart(monkeypatch):
    calls = []

    def overlay(*args):
        calls.append(args)
        return {"status": "READY", "source_kind": "FUTU_SDK_DIRECT_QFQ_20261026_EXACT76"}

    monkeypatch.setattr(history, "_admitted_direct_qfq", overlay)
    default = history._profile_direct_qfq("root", "cache", "300071.SZ", "20260101", "20261028", numeric283_chart=False)
    chart = history._profile_direct_qfq("root", "cache", "300071.SZ", "20260101", "20261028", numeric283_chart=True)
    assert default["source_kind"] == "FUTU_SDK_DIRECT_QFQ_20261026_EXACT76"
    assert chart is None
    assert len(calls) == 1


def test_r19_dispatch_stays_on_its_existing_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(history, "_request", lambda *args: calls.append(args))
    profile = types.ModuleType("apps.api.v4_api.a_share_r19_profile")
    profile.read_profile = lambda *args: {"status": "R19_DISPATCHED"}
    monkeypatch.setitem(sys.modules, profile.__name__, profile)

    answer = history.read_history(None, "600025.SH", "20260101", "20261027", "R19_FROZEN_151_20261027")
    assert answer == {"status": "R19_DISPATCHED"}
    assert calls == [("600025.SH", "20260101", "20261027", history.VERSION)]


def test_static_builder_reuses_pinned_membership_and_isolates_bound_chart_renderer():
    contract_raw = STATIC_BUILDER.must_pin(
        STATIC_BUILDER.CONTRACT_PATH,
        STATIC_BUILDER.EXPECTED_CONTRACT_SHA,
        "chart-fix contract",
    )
    payload, _ = STATIC_BUILDER.build_payload(json.loads(contract_raw))
    payload_raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    pinned_payload = STATIC_BUILDER.must_pin(
        STATIC_BUILDER.SOURCE_DAILY.parent / STATIC_BUILDER.JSON_NAME,
        STATIC_BUILDER.EXPECTED_STATIC_PINS[STATIC_BUILDER.JSON_NAME],
        "existing numeric-283 payload",
    )
    assert payload_raw == pinned_payload

    source = STATIC_BUILDER.must_pin(
        STATIC_BUILDER.SOURCE_DAILY.parent / "r19-chart.js",
        STATIC_BUILDER.EXPECTED_STATIC_PINS["r19-chart.js"],
        "pinned R19 renderer",
    )
    renderer = STATIC_BUILDER.derive_chart_renderer(source).decode("utf-8")
    assert "window.Numeric283Chart" in renderer
    assert "window.R19Chart" not in renderer
    assert "getElementById('r19'+id)" not in renderer
    assert renderer.rstrip().endswith("window.Numeric283Chart.bind();")
    markup = STATIC_BUILDER.build_chart_markup()
    assert 'id="dailyNumeric283ChartPanel"' in markup
    assert 'numeric283-chart-trigger{white-space:nowrap}' in markup
