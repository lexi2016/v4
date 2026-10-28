from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import json
import sys
import types
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

APP = Path(__file__).resolve().parents[1]
RELEASE_ID = "hk-research-calendar-all-r1-20261007"

# This stub makes the dispatcher integration use the explicit fake executor
# below; no registered workload module or producer is imported or launched.
_executor_registry_stub = types.ModuleType("infrastructure.scheduling.executor_registry")
_executor_registry_stub.WorkloadExecutionError = type("WorkloadExecutionError", (Exception,), {})
_MISSING = object()


@contextmanager
def _temporary_executor_registry_stub():
    module_name = "infrastructure.scheduling.executor_registry"
    previous = sys.modules.get(module_name, _MISSING)
    if previous is _MISSING:
        sys.modules[module_name] = _executor_registry_stub
    try:
        yield
    finally:
        if previous is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


@contextmanager
def _temporary_stage_package():
    prefix = "stage_center"
    previous = {
        name: module
        for name, module in sys.modules.items()
        if name == prefix or name.startswith(prefix + ".")
    }
    if prefix not in sys.modules:
        stage_package = types.ModuleType(prefix)
        stage_package.__path__ = [str(APP / prefix)]
        stage_package.__package__ = prefix
        sys.modules[prefix] = stage_package
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if (name == prefix or name.startswith(prefix + ".")) and name not in previous:
                sys.modules.pop(name, None)
        for name, module in previous.items():
            sys.modules[name] = module

# Load the Stage scheduler under its real package path without running the
# package initializer, which imports selection/producer modules outside this
# candidate's test boundary.
with _temporary_executor_registry_stub():
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
    from infrastructure.runtime_graph._service_parts.calendar import (
        __calendar_decision_body,
        __next_market_trade_date_body,
    )
    from infrastructure.runtime_graph.v35_topology import load_v35_topology
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.dispatcher import _RUNTIME_IDENTITY_FILES, dispatch_due

with _temporary_stage_package():
    from stage_center.calendar import eligible_stage_markets
    from stage_center.scheduler import evaluate_due


TARGET_POLICIES = {
    "research_panel_daily_hk": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "research_panel_runtime_evidence": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "review_core_pool_pipeline": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "hk_connect_close_review": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "preselection_pools": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "daily_materialize": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "hk_auction_0920": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "stage_workbench": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "fupan_review_start": RunPolicy.HK_SECURITIES_TRADE_DAY,
}
EXPECTED_BY_SLOT = {
    "0915": {"hk_auction_0920"},
    "1555": {"fupan_review_start"},
    "1610": {"hk_connect_close_review"},
    "1720": {"research_panel_daily_hk"},
    "1730": {"research_panel_runtime_evidence", "preselection_pools"},
    "2115": {"review_core_pool_pipeline"},
    "2140": {"daily_materialize"},
}
HK_ONLY_DATES = ("20261005", "20261006", "20261007")
A_ONLY_DATE = "20260403"
NONTRADING_DATE = "20261004"


@pytest.fixture
def candidate_release_identity(monkeypatch, tmp_path):
    entries = []
    for relative in sorted(_RUNTIME_IDENTITY_FILES):
        path = APP / relative
        content = path.read_bytes()
        entries.append(
            {
                "kind": "file",
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    inventory = {
        "entry_count": len(entries),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "entries": entries,
    }
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(APP), "release_id": RELEASE_ID},
        "application_inventory": inventory,
    }
    receipt_root = tmp_path / "receipts" / RELEASE_ID
    manifest_path = receipt_root / "release-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest_path.write_bytes(raw)
    values = {
        "V35_APP_ROOT": str(APP),
        "V35_RELEASE_ID": RELEASE_ID,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(raw).hexdigest(),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return {**values, "receipt_root": str(receipt_root)}


def _safe_fake_executor(calls):
    def execute(workload, request, decision):
        calls.append(
            {
                "workload_id": workload.workload_id,
                "date": request.business_date,
                "slot": request.slot,
                "eligible_markets": list(decision.eligible_markets),
            }
        )
        return {
            "status": "SUCCEEDED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "executor": "candidate_test_fake_no_process",
        }

    return execute


def _request(date8: str, slot: str) -> DispatchRequest:
    return DispatchRequest(
        scheduled_date=date8,
        business_date=date8,
        target_date=date8,
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _write_receipt(receipt, *, scenario: str, receipt_root: Path) -> Path:
    path = receipt_root / "dispatcher" / scenario / receipt.business_date / f"{receipt.slot}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.to_dict()
    payload["candidate_only"] = True
    payload["executor_kind"] = "fake_no_process"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _calendar_scope():
    def valid_date(value):
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")

    return {
        "_valid_date": valid_date,
        "RunPolicy": RunPolicy,
        "MarketScope": MarketScope,
        "SessionRequirement": SessionRequirement,
        "evaluate_run_policy": evaluate_run_policy,
        "load_market_calendar": load_market_calendar,
        "resolve_market_states": resolve_market_states,
        "TradingDayState": TradingDayState,
        "datetime": datetime,
        "timedelta": __import__("datetime").timedelta,
        "range": range,
        "ValueError": ValueError,
        "Exception": Exception,
        "getattr": getattr,
        "str": str,
    }


def _daily_materialize_calendar_function():
    path = APP / "ops/daily_materialize.py"
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_serialize_decision", "_evaluate_calendar"}
    }
    isolated = ast.Module(
        body=[functions["_serialize_decision"], functions["_evaluate_calendar"]],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(isolated, str(path), "exec"), namespace)
    return namespace["_evaluate_calendar"]


def _task_status_schedule_date_function():
    path = APP / "domains/task_status.py"
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_schedule_date_is_eligible"
    )
    namespace = {
        "RunPolicy": RunPolicy,
        "TradingDayState": TradingDayState,
        "load_market_calendar": load_market_calendar,
        "resolve_market_states": resolve_market_states,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_schedule_date_is_eligible"]


def _target_date_for_node_function(next_market_trade_date=None):
    path = APP / "infrastructure/runtime_graph/service.py"
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_target_date_for_node"
    )
    scope = _calendar_scope()
    if next_market_trade_date is None:
        next_market_trade_date = lambda business_date, market: __next_market_trade_date_body(
            scope, business_date, market
        )
    namespace = {
        "_next_market_trade_date": next_market_trade_date,
        "_next_v35_trade_date": lambda business_date: f"v35:{business_date}",
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_target_date_for_node"]


def test_all_hk_research_workloads_dispatch_on_hk_only_dates(candidate_release_identity):
    receipt_root = Path(candidate_release_identity["receipt_root"])
    catalog = load_workload_catalog()
    by_id = {workload.workload_id: workload for workload in catalog.workloads}
    assert set(TARGET_POLICIES) <= set(by_id)
    for workload_id, expected_policy in TARGET_POLICIES.items():
        workload = by_id[workload_id]
        assert workload.run_policy is expected_policy
        assert workload.safety.production_allowed is False
        assert workload.safety.buy_gate_updated is False
        assert workload.safety.orders_sent is False

    calls = []
    executor = _safe_fake_executor(calls)
    selected_across_dates = set()
    receipts = []
    for date8 in HK_ONLY_DATES:
        states = resolve_market_states(load_market_calendar(), date8)
        assert states["a_share"] is TradingDayState.NON_TRADING_DAY
        assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
        assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY
        for slot, expected in EXPECTED_BY_SLOT.items():
            result = dispatch_due(_request(date8, slot), catalog, executor)
            selected = set(result.selected_workload_ids)
            started = set(result.started_workload_ids)
            assert expected <= selected, (date8, slot, expected, selected, result.to_dict())
            assert expected <= started, (date8, slot, expected, started, result.to_dict())
            assert result.status == "SUCCEEDED"
            assert result.production_allowed is False
            assert result.buy_gate_updated is False
            assert result.orders_sent is False
            selected_across_dates.update(selected)
            receipts.append(
                _write_receipt(result, scenario="hk_only", receipt_root=receipt_root)
            )

    target_ids = set(TARGET_POLICIES) - {"stage_workbench"}
    assert by_id["stage_workbench"].enabled is False
    assert target_ids <= selected_across_dates
    assert all(call["workload_id"] in selected_across_dates for call in calls)
    assert len(receipts) == len(HK_ONLY_DATES) * len(EXPECTED_BY_SLOT)
    index = receipt_root / "dispatcher" / "hk_only" / "index.json"
    index.write_text(
        json.dumps(
            {
                "release_id": RELEASE_ID,
                "dates": list(HK_ONLY_DATES),
                "slots": list(EXPECTED_BY_SLOT),
                "target_workload_ids": sorted(target_ids),
                "receipt_paths": [
                    str(path.relative_to(receipt_root.parent.parent)) for path in receipts
                ],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_nontrading_and_a_only_dates_keep_market_boundaries(candidate_release_identity):
    receipt_root = Path(candidate_release_identity["receipt_root"])
    catalog = load_workload_catalog()
    calls = []
    executor = _safe_fake_executor(calls)
    target_ids = set(TARGET_POLICIES)

    for slot in EXPECTED_BY_SLOT:
        result = dispatch_due(_request(NONTRADING_DATE, slot), catalog, executor)
        assert not (target_ids & set(result.selected_workload_ids))
        assert not (target_ids & set(result.started_workload_ids))
        assert result.production_allowed is False
        assert result.buy_gate_updated is False
        assert result.orders_sent is False
        _write_receipt(result, scenario="nontrading", receipt_root=receipt_root)

    states = resolve_market_states(load_market_calendar(), A_ONLY_DATE)
    assert states["a_share"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_securities"] is TradingDayState.NON_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY

    close = dispatch_due(_request(A_ONLY_DATE, "1605"), catalog, executor)
    assert "a_share_close_review" in close.selected_workload_ids
    assert "a_share_close_review" in close.started_workload_ids
    assert "hk_connect_close_review" not in close.selected_workload_ids

    cross = dispatch_due(_request(A_ONLY_DATE, "1730"), catalog, executor)
    assert {"research_panel_runtime_evidence", "preselection_pools"} <= set(cross.selected_workload_ids)
    assert {"research_panel_runtime_evidence", "preselection_pools"} <= set(cross.started_workload_ids)
    assert "research_panel_daily_hk" not in cross.selected_workload_ids
    assert "fupan_review_start" not in dispatch_due(
        _request(A_ONLY_DATE, "1555"), catalog, executor
    ).selected_workload_ids
    _write_receipt(close, scenario="a_only", receipt_root=receipt_root)
    _write_receipt(cross, scenario="a_only", receipt_root=receipt_root)

    # Recreate an actual dispatcher request with the old Connect policy to
    # prove that its closed-day semantics remain independent of HK securities.
    connect_only = replace(
        by_workload_id(catalog, "fupan_review_start"),
        run_policy=RunPolicy.HK_CONNECT_TRADE_DAY,
    )
    connect_catalog = replace(catalog, workloads=(connect_only,))
    call_count = len(calls)
    connect_result = dispatch_due(_request("20261005", "1555"), connect_catalog, executor)
    assert connect_result.selected_workload_ids == ()
    assert connect_result.started_workload_ids == ()
    assert connect_result.blocked_markets == ("hk_connect",)
    assert len(calls) == call_count
    _write_receipt(connect_result, scenario="connect_preserved", receipt_root=receipt_root)


def by_workload_id(catalog, workload_id):
    return next(item for item in catalog.workloads if item.workload_id == workload_id)


def test_runtime_graph_calendar_api_and_materializer_internal_gate(candidate_release_identity):
    scope = _calendar_scope()
    hk_only = __calendar_decision_body(
        scope, "hk_securities_trade_day", "20261005", evaluator=evaluate_run_policy
    )
    connect_closed = __calendar_decision_body(
        scope, "hk_connect_trade_day", "20261005", evaluator=evaluate_run_policy
    )
    cross_hk_only = __calendar_decision_body(
        scope, "a_or_hk_securities_trade_day", "20261005", evaluator=evaluate_run_policy
    )
    cross_connect = __calendar_decision_body(
        scope, "a_or_hk_connect_trade_day", "20261005", evaluator=evaluate_run_policy
    )
    assert hk_only == {"should_run": True, "status": "TRADING_DAY", "business_date": "20261005"}
    assert connect_closed == {"should_run": False, "status": "NON_TRADING_DAY"}
    assert cross_hk_only == {"should_run": True, "status": "PARTIAL_MARKET", "business_date": "20261005"}
    assert cross_connect == {"should_run": False, "status": "NON_TRADING_DAY"}

    assert __next_market_trade_date_body(scope, "20261001", "hk_securities") == "20261002"
    assert __next_market_trade_date_body(scope, "20261001", "hk_connect") == "20261008"
    with pytest.raises(ValueError, match="RUNTIME_GRAPH_MARKET_INVALID"):
        __next_market_trade_date_body(scope, "20261001", "other")

    evaluate_materializer = _daily_materialize_calendar_function()
    materialized = evaluate_materializer("20261005")
    assert materialized["decision"].eligible is True
    assert materialized["decision"].policy is RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY
    assert materialized["serialized"]["market_states"] == {
        "a_share": "NON_TRADING_DAY",
        "hk_securities": "FULL_TRADING_DAY",
    }
    assert materialized["overall_status"] == "COMPLETED"

    no_market = evaluate_materializer(NONTRADING_DATE)
    assert no_market["decision"].eligible is False
    assert no_market["overall_status"] == "NON_TRADING_DAY"
    a_only = evaluate_materializer(A_ONLY_DATE)
    assert a_only["decision"].eligible is True
    assert a_only["decision"].eligible_markets == ("a_share",)
    source_text = (APP / "ops/daily_materialize.py").read_text(encoding="utf-8")
    assert "A_OR_HK_CONNECT_TRADE_DAY" not in source_text


def test_stage_scheduler_and_topology_remain_hk_securities_aware(candidate_release_identity):
    assert eligible_stage_markets(("HK_CONNECT",), "20261005") == ("HK_CONNECT",)
    at_cutoff = datetime(2026, 10, 5, 15, 55, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    decision = evaluate_due("STAGE_1545_1555", "20261005", at_cutoff)
    assert decision.status == "DUE"
    assert decision.calendar["a_share"] == "NON_TRADING_DAY"
    assert decision.calendar["hk_securities"] == "FULL_TRADING_DAY"
    assert decision.calendar["hk_connect"] == "NON_TRADING_DAY"
    closed = evaluate_due(
        "STAGE_1545_1555",
        NONTRADING_DATE,
        datetime(2026, 10, 4, 15, 55, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert closed.status == "SKIPPED_NON_TRADING_DAY"

    topology = load_v35_topology()
    workload_nodes = [
        node
        for node in topology["nodes"]
        if node.get("type") == "workload" and node.get("workload_id") in TARGET_POLICIES
    ]
    for node in workload_nodes:
        assert node["run_policy"] == TARGET_POLICIES[node["workload_id"]].value
    timeline9 = next(node for node in topology["timeline_nodes"] if node["position"] == 9)
    assert timeline9["workload_id"] == "hk_connect_close_review"
    assert timeline9["planned_slot"] == "1610"
    assert timeline9["workload"]["slot"] == "1610"
    assert "/1610/" in timeline9["artifact_trio"]["artifact"]
    assert all(flag is False for flag in topology["safety"].values())


def test_task_status_date_gate_uses_hk_securities_and_preserves_connect():
    catalog = load_workload_catalog()
    by_id = {workload.workload_id: workload for workload in catalog.workloads}
    eligible = _task_status_schedule_date_function()
    calendar = load_market_calendar()

    assert eligible(by_id["research_panel_daily_hk"], "20261002", calendar=calendar)
    assert not eligible(by_id["research_panel_daily_hk"], NONTRADING_DATE, calendar=calendar)
    assert eligible(by_id["fupan_review_start"], "20261002", calendar=calendar)
    assert not eligible(by_id["fupan_review_start"], A_ONLY_DATE, calendar=calendar)
    assert eligible(by_id["daily_materialize"], A_ONLY_DATE, calendar=calendar)
    assert not eligible(by_id["daily_materialize"], NONTRADING_DATE, calendar=calendar)

    requested_sessions = []
    target_date = _target_date_for_node_function(
        lambda date, market: requested_sessions.append((date, market)) or "next-session"
    )
    assert target_date("hkconnect_d1_top100_prob_active", "20260925") == "next-session"
    assert requested_sessions.pop() == ("20260925", "hk_connect")
    assert target_date("ashare_v193_slot_selector_premarket", "20260925") == "next-session"
    assert requested_sessions.pop() == ("20260925", "a_share")
    assert target_date("other_node", "20260925") == "v35:20260925"
