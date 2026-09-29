"""Run one fixed V3.5 scheduled slot through the runtime dispatcher."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from contracts.trading_calendar import (
    MarketCalendar,
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry


SHANGHAI = ZoneInfo("Asia/Shanghai")
RESULT_SCHEMA = "v3_5.scheduled_slot_result.v1"


def _with_runtime_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep success and failure JSON envelopes structurally identical."""

    result = dict(payload)
    for field in ("failure_class", "retry_after", "release_id", "upstream_fingerprint", "app_root",
                  "release_manifest_path", "release_manifest_sha256"):
        value = result.get(field)
        result[field] = value if value not in (None, "") else None
    try:
        result["attempt"] = max(0, int(result.get("attempt") or 0))
    except (TypeError, ValueError):
        result["attempt"] = 0
    return result

# Fixed dispatcher slots.  16:05 remains the independent A-share graph node;
# HK Connect's formal close review has its own 16:08 slot.
ALL_SLOTS: tuple[str, ...] = (
    "0415", "0515", "0700", "0800", "0830", "0840", "0900", "0901", "0915", "0925", "0930", "0935", "0940",
    "0945", "1000", "1030", "1100", "1130", "1200", "1300", "1315",
    "1400", "1500", "1530", "1555", "1600", "1605", "1608", "1700", "1710", "1720",
    "1730", "1800", "1900", "2000", "2001", "2030", "2040", "2050",
    "2100", "2105", "2108", "2110", "2115", "2140", "2200",
    "2300",
)
SLOT_COUNT = len(ALL_SLOTS)
PRESELECTION_SLOTS = frozenset({"1730", "1800"})
NEXT_TARGET_SLOTS = frozenset({"1730", "1800", "2001", "2115", "2140"})
ZERO_EXIT_STATUSES = frozenset(
    {
        "NON_TRADING_DAY",
        "NON_TRADING_DAY_CADENCE",
        "NO_DUE_WORKLOADS",
        "NO_ELIGIBLE_WORKLOADS",
        "CONCURRENCY_SKIPPED",
        "DRY_RUN_SELECTED",
        "SUCCEEDED",
        "DUPLICATE_WORKLOAD_SKIPPED",
    }
)


def _date8(value: str, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"{name}_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{name}_INVALID") from error
    return value


def next_trade_day(
    business_date: str,
    *,
    calendar: MarketCalendar | None = None,
    max_scan_days: int = 370,
) -> str:
    _date8(business_date, name="BUSINESS_DATE")
    calendar = calendar or load_market_calendar()
    current = date(int(business_date[:4]), int(business_date[4:6]), int(business_date[6:]))
    for offset in range(1, max(1, int(max_scan_days)) + 1):
        candidate = (current + timedelta(days=offset)).strftime("%Y%m%d")
        states = resolve_market_states(calendar, candidate)
        if any(
            states[key] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
            for key in ("a_share", "hk_connect")
        ):
            return candidate
    raise ValueError("NEXT_TRADE_DAY_UNAVAILABLE")


def compute_dates(*, business_date: str, slot: str, calendar: MarketCalendar | None = None) -> dict[str, str]:
    if slot not in ALL_SLOTS:
        raise ValueError("UNKNOWN_SLOT")
    business_date = _date8(business_date, name="BUSINESS_DATE")
    calendar = calendar or load_market_calendar()
    states = resolve_market_states(calendar, business_date)
    if all(state is TradingDayState.UNKNOWN for state in states.values()):
        raise ValueError("CALENDAR_UNKNOWN")
    target = next_trade_day(business_date, calendar=calendar) if slot in NEXT_TARGET_SLOTS else business_date
    return {"scheduled_date": business_date, "business_date": business_date, "target_date": target}


def run_scheduled_slot(
    *,
    data_root: Path,
    slot: str,
    business_date: str,
    scheduled_date: str,
    target_date: str,
    ledger_root: Path,
    timeout_seconds: float = 600.0,
    dry_run: bool = False,
    shared_data_root: Path | None = None,
    hk_universe_root: Path | None = None,
    shared_package_root: Path | None = None,
    hk_0_2_python_executable: Path | None = None,
    selector_data_root: Path | None = None,
    preselection_input_root: Path | None = None,
    stage_selection_root: Path | None = None,
    workload_guard: Callable[[Any, DispatchRequest, Any], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    if slot not in ALL_SLOTS:
        raise ValueError("UNKNOWN_SLOT")
    request = DispatchRequest(
        scheduled_date=_date8(scheduled_date, name="SCHEDULED_DATE"),
        business_date=_date8(business_date, name="BUSINESS_DATE"),
        target_date=_date8(target_date, name="TARGET_DATE"),
        slot=slot,
        mode=DispatchMode.LIVE,
    )
    registry = FixedExecutorRegistry(
        data_root=data_root,
        shared_data_root=shared_data_root,
        hk_universe_root=hk_universe_root,
        shared_package_root=shared_package_root,
        hk_0_2_python_executable=hk_0_2_python_executable,
        selector_data_root=selector_data_root,
        preselection_input_root=preselection_input_root,
        stage_selection_root=stage_selection_root,
        timeout_seconds=timeout_seconds,
        repo_root=Path(__file__).resolve().parents[1],
    )
    executor = _noop_executor if dry_run else registry
    if not dry_run and workload_guard is not None:
        def guarded_executor(workload, dispatch_request, decision):
            gate = workload_guard(workload, dispatch_request, decision)
            output = registry(workload, dispatch_request, decision)
            if gate is not None and isinstance(output, dict):
                output = dict(output)
                output.setdefault("stage_gate", gate)
            return output

        executor = guarded_executor
    receipt = dispatch_due(
        request,
        load_workload_catalog(),
        executor,
        ledger=ExecutionLedger(ledger_root),
        dry_run=dry_run,
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "slot": slot,
        "business_date": business_date,
        "scheduled_date": scheduled_date,
        "target_date": target_date,
        "status": receipt.status,
        "run_id": receipt.run_id,
        "selected_workload_ids": list(receipt.selected_workload_ids),
        "started_workload_ids": list(receipt.started_workload_ids),
        "receipt_path": receipt.receipt_path,
        "failure_class": receipt.failure_class or None,
        "retry_after": receipt.retry_after or None,
        "release_id": receipt.release_id or None,
        "app_root": receipt.app_root or None,
        "release_manifest_path": receipt.release_manifest_path or None,
        "release_manifest_sha256": receipt.release_manifest_sha256 or None,
        "upstream_fingerprint": receipt.upstream_fingerprint or None,
        "attempt": max(0, int(receipt.attempt or 0)),
        "production_allowed": receipt.production_allowed,
        "buy_gate_updated": receipt.buy_gate_updated,
        "orders_sent": receipt.orders_sent,
    }


def _noop_executor(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("dry-run scheduled slot does not execute workloads")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one fixed V3.5 scheduled workload slot")
    parser.add_argument("--slot", required=True, choices=ALL_SLOTS)
    parser.add_argument("--date", help="business date YYYYMMDD (default: today Shanghai)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", type=Path, default=Path(".runtime") / "dispatcher")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--hk-universe-root", type=Path)
    parser.add_argument("--shared-package-root", type=Path)
    parser.add_argument(
        "--hk-0-2-python",
        type=Path,
        default=(
            Path(os.environ["V35_HK_0_2_PYTHON"])
            if os.environ.get("V35_HK_0_2_PYTHON")
            else None
        ),
    )
    parser.add_argument("--stage-selection-root", type=Path)
    args = parser.parse_args(argv)
    business_date = args.date or datetime.now(SHANGHAI).strftime("%Y%m%d")
    try:
        dates = compute_dates(business_date=business_date, slot=args.slot)
        result = run_scheduled_slot(
            data_root=args.data_root,
            slot=args.slot,
            ledger_root=args.ledger_root,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
            shared_data_root=args.shared_data_root,
            hk_universe_root=args.hk_universe_root,
            shared_package_root=args.shared_package_root,
            hk_0_2_python_executable=args.hk_0_2_python,
            stage_selection_root=args.stage_selection_root,
            **dates,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"scheduled slot failed: {type(error).__name__}: {error}", file=sys.stderr)
        result = {
            "schema_version": RESULT_SCHEMA,
            "slot": args.slot,
            "status": "FAILED",
            "reason": f"{type(error).__name__}: {error}",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(_with_runtime_metadata(result), ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(_with_runtime_metadata(result), ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in ZERO_EXIT_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
