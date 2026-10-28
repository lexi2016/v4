from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from contracts.trading_calendar import (
    MarketScope,
    RunPolicy,
    SessionRequirement,
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from domains.runtime_policy import evaluate_run_policy
from infrastructure.scheduling import dispatcher
from infrastructure.scheduling.catalog import load_workload_catalog


OBSERVATION_DATE = "20260925"
HK_CLOSED_DATE = "20260217"
WORKLOAD_ID = "hk_auction_0920"


def _observation_catalog():
    loaded = load_workload_catalog()
    workload = next(item for item in loaded.workloads if item.workload_id == WORKLOAD_ID)
    return replace(loaded, workloads=(workload,))


@pytest.fixture
def release_identity(monkeypatch, tmp_path):
    app_root = Path(__file__).resolve().parents[1]
    entries = [
        {
            "path": relative,
            "kind": "file",
            "sha256": hashlib.sha256((app_root / relative).read_bytes()).hexdigest(),
            "size": (app_root / relative).stat().st_size,
        }
        for relative in dispatcher._RUNTIME_IDENTITY_FILES
    ]
    inventory_sha = hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(app_root), "release_id": "test-only-release"},
        "application_inventory": {
            "entries": entries,
            "entry_count": len(entries),
            "aggregate_sha256": inventory_sha,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    manifest = tmp_path / "release-manifest.json"
    manifest.write_bytes(raw)
    for name, value in {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": "test-only-release",
        "V35_RELEASE_MANIFEST_PATH": str(manifest),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(raw).hexdigest(),
    }.items():
        monkeypatch.setenv(name, value)


def test_observation_policy_uses_hk_securities_without_relabeling_southbound():
    states = resolve_market_states(load_market_calendar(), OBSERVATION_DATE)
    assert states["a_share"] is TradingDayState.NON_TRADING_DAY
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY

    observation = evaluate_run_policy(
        RunPolicy.HK_SECURITIES_TRADE_DAY,
        OBSERVATION_DATE,
        "0915",
        market_scope=MarketScope.HK_CONNECT,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    assert observation.eligible is True
    assert observation.eligible_markets == ("hk_securities",)
    assert observation.market_states == {"hk_securities": "FULL_TRADING_DAY"}

    southbound = evaluate_run_policy(
        RunPolicy.HK_CONNECT_TRADE_DAY,
        OBSERVATION_DATE,
        "0915",
        market_scope=MarketScope.HK_CONNECT,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    assert southbound.eligible is False
    assert southbound.blocked_markets == ("hk_connect",)

    ashare = evaluate_run_policy(
        RunPolicy.A_SHARE_TRADE_DAY,
        OBSERVATION_DATE,
        "0915",
        market_scope=MarketScope.A_SHARE,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    assert ashare.eligible is False
    assert ashare.blocked_markets == ("a_share",)


def test_existing_dispatcher_selects_observation_capture_on_hk_only_day(release_identity):
    from infrastructure.scheduling.dispatcher import dispatch_due

    request = DispatchRequest(
        scheduled_date=OBSERVATION_DATE,
        business_date=OBSERVATION_DATE,
        target_date=OBSERVATION_DATE,
        slot="0915",
        mode=DispatchMode.LIVE,
    )
    receipt = dispatch_due(
        request,
        _observation_catalog(),
        lambda *_args: pytest.fail("dry-run must not call the existing capture owner"),
        dry_run=True,
    )
    assert receipt.status == "DRY_RUN_SELECTED"
    assert receipt.selected_workload_ids == (WORKLOAD_ID,)
    assert receipt.eligible_markets == ("hk_securities",)


def test_existing_dispatcher_skips_when_hk_securities_are_closed(release_identity):
    from infrastructure.scheduling.dispatcher import dispatch_due

    request = DispatchRequest(
        scheduled_date=HK_CLOSED_DATE,
        business_date=HK_CLOSED_DATE,
        target_date=HK_CLOSED_DATE,
        slot="0915",
        mode=DispatchMode.LIVE,
    )
    receipt = dispatch_due(
        request,
        _observation_catalog(),
        lambda *_args: pytest.fail("closed-day dry-run must not invoke a collector"),
        dry_run=True,
    )
    assert receipt.status == "NON_TRADING_DAY"
    assert receipt.selected_workload_ids == ()
