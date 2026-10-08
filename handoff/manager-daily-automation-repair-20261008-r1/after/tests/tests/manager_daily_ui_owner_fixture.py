"""Python-owned DTO fixture for the isolated daily manager UI tests.

The US daily run is produced by the real ``refresh_us_mapping_research`` owner,
real bridge, synthetic exact-session ResearchPeripheralStore, and its original
readback adapter.  Plan readback is produced by the store-backed original
workspace plan owner.  Synthetic inputs are explicitly test-only.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from datetime import timedelta
from zoneinfo import ZoneInfo

from infrastructure.research_peripheral_store import ResearchPeripheralStore
from v4.manager_research import us_mapping_research, workspace
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import FLAGS, HK


def _synthetic_us_payload(session_date: str, positive_changes: dict[str, float]) -> dict:
    """TEST_FIXTURE exact-session payload accepted by the original store reader."""
    from infrastructure.research_peripheral_store import (
        CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP, _CANONICAL_SYMBOLS,
        _MARKET_MAPPING_VERSION, _MARKET_SNAPSHOT_SCHEMA_VERSION, _SCHEMA_VERSION,
    )

    us = ZoneInfo("America/New_York")
    day = datetime.strptime(session_date, "%Y%m%d")
    captured = datetime(day.year, day.month, day.day, 16, 15, 3, tzinfo=us)
    captured_text = captured.isoformat()
    symbols = sorted(_CANONICAL_SYMBOLS)
    changes = {symbol: float(positive_changes.get(symbol, 0.0)) for symbol in symbols}
    quotes = [{
        "symbol": symbol, "exchange": "US", "session_date": session_date,
        "session_time": "16:00:00", "last": 100.0 * (1.0 + changes[symbol] / 100.0),
        "previous_close": 100.0, "change_pct": changes[symbol],
        "provider": "ISOLATED_TEST_FIXTURE",
    } for symbol in symbols]
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
        "capture_window_start": datetime(day.year, day.month, day.day, 16, 15, tzinfo=us).isoformat(),
        "capture_window_end": datetime(day.year, day.month, day.day, 16, 20, tzinfo=us).isoformat(),
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


def _workspace_base(date: str) -> dict:
    cutoff = "2026-10-08T10:00:00+08:00"
    return {
        "target_trade_date": date,
        "input_identity": "a" * 64,
        "semantic_version": "fixture",
        "plan_context": {"research_cutoff": cutoff},
        "gaps": [],
        "stocks": [],
        "existing_material_coverage": {},
        "summary": {},
        "lanes": [],
        **FLAGS,
    }


def owner_fixture() -> dict:
    date = "20261008"
    execution_at = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    reviewed = {
        "schema_version": "TEST_FIXTURE",
        "artifact_sha256": "d" * 64,
        "cards": [{
            "daily_match_symbols": ["LITE"],
            "hk_symbol": "HK.06166",
            "hk_name": "Synthetic issuer",
            "research_priority": "PRIORITY",
            "relationship_type": "PRODUCT_PEER",
            "reason": "TEST_FIXTURE_ORIGINAL_OWNER_RELATION_REASON",
            "maturity": "TEST_FIXTURE",
            "limitations": ["synthetic test fixture; no natural market evidence"],
            "official_sources": [],
        }],
    }

    with TemporaryDirectory(prefix="manager-daily-ui-owner-") as directory:
        root = Path(directory)
        source_root = root / "research-peripheral"
        ResearchPeripheralStore(source_root).publish(
            _synthetic_us_payload("20261007", {"LITE": 5.125}))
        reader = ResearchPeripheralUsMarketReader(source_root)
        master = root / "security-master"
        master.mkdir()
        service = ManagerResearchJobService(
            ManagerResearchStore(root / "manager-state"), None, None,
            existing_research_source=None,
            workspace_security_master_root=master,
            workspace_us_market_reader=reader,
        )
        prior_reviewed = us_mapping_research._read_reviewed
        prior_available = us_mapping_research._relation_available_at
        prior_workspace = workspace.get_workspace
        prior_now = workspace._now
        try:
            us_mapping_research._read_reviewed = lambda: reviewed
            us_mapping_research._relation_available_at = lambda _reviewed: (
                datetime(2026, 10, 1, 0, 0, tzinfo=HK), None)
            daily_result = service.refresh_us_mapping_research(
                date,
                now=execution_at,
                timeout_seconds=2.0,
                execution_context={
                    "trigger_kind": "SCHEDULED",
                    "timing": "LATE_CATCHUP",
                    "scheduled_for": "2026-10-08T10:00:00+08:00",
                    "trigger_id": "b" * 64,
                    "natural_run_verified": False,
                },
            )
            mapping = us_mapping_research.read_workspace_mapping(service, date)

            workspace.get_workspace = lambda *_args, **_kwargs: _workspace_base(date)
            workspace._now = lambda: "2026-10-08T01:59:58+00:00"
            saved = workspace.refresh_workspace_plan(service, date)
            product_run = saved["plan_product"]["run_id"]
            latest_path = service.store.root / "workspace_plan_runs" / date / "latest.json"
            latest = service.store._read(latest_path)
            failed = workspace.seal_attempt({
                **latest,
                "run_id": "9" * 32,
                "state": "FAILED",
                "started_at": "2026-10-08T02:05:00+00:00",
                "finished_at": "2026-10-08T02:05:01+00:00",
                "failure_reasons": ["TEST_FIXTURE_LATER_ATTEMPT_FAILURE"],
            })
            service.store._write_atomic(latest_path, failed)
            current = _workspace_base(date)
            plan_readback = workspace._readback_plan(service.store, date, current)
            assert plan_readback["plan_product"]["run_readback"]["status"] == "VERIFIED"
            assert plan_readback["plan_product"]["run_id"] == product_run
            assert plan_readback["workspace_plan_attempt"]["state"] == "FAILED"
            assert mapping["daily_run"]["status"] == "COMPLETED", mapping["daily_run"]
            assert mapping["daily_run"]["matches"][0]["us_symbol"] == "LITE"
            assert daily_result["run_id"] == mapping["daily_run"]["run_id"]
            return {
                "target_trade_date": plan_readback["target_trade_date"],
                "input_identity": plan_readback["input_identity"],
                "us_mapping_research": mapping,
                "plan_product": plan_readback["plan_product"],
                "workspace_plan_attempt": plan_readback["workspace_plan_attempt"],
            }
        finally:
            us_mapping_research._read_reviewed = prior_reviewed
            us_mapping_research._relation_available_at = prior_available
            workspace.get_workspace = prior_workspace
            workspace._now = prior_now
            service.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "--fixture":
        raise SystemExit("Usage: manager_daily_ui_owner_fixture.py --fixture")
    print(json.dumps(owner_fixture(), ensure_ascii=False, allow_nan=False))
