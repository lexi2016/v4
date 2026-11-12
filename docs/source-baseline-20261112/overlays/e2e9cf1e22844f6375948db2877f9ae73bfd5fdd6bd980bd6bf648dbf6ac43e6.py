"""Dispatch one registered US market workload through the V4 runtime spine.

This is an evidence-ready owner wrapper.  It narrows the existing runtime
catalog in memory before calling the existing dispatcher, so the multiplexed
daily catalog remains available to its existing owner.  The wrapper does not
own a producer, alter the catalog on disk, or activate a LaunchAgent.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import DispatchMode, DispatchRequest, RuntimeCatalog, WorkloadDefinition
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops.run_scheduled_slot import compute_dates


SHANGHAI = ZoneInfo("Asia/Shanghai")
US_MARKET_WORKLOAD_ID = "us_market_digest"
US_MARKET_OWNER_ID = "v4_dispatcher.us_market_digest"
US_MARKET_SLOTS: tuple[str, ...] = ("0415", "0515", "2100", "2200")
US_MARKET_SLOT_SET = frozenset(US_MARKET_SLOTS)
RESULT_SCHEMA = "v4.us_market_slot_result.v1"
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


def _validate_slot(slot: str) -> str:
    if not isinstance(slot, str) or slot not in US_MARKET_SLOT_SET:
        raise ValueError("US_SLOT_NOT_ALLOWED")
    return slot


def _registered_us_workload(catalog: RuntimeCatalog) -> WorkloadDefinition:
    matches = tuple(
        workload
        for workload in catalog.workloads
        if workload.workload_id == US_MARKET_WORKLOAD_ID
    )
    if len(matches) != 1:
        raise ValueError("US_WORKLOAD_NOT_REGISTERED")
    workload = matches[0]
    if workload.owner_id != US_MARKET_OWNER_ID:
        raise ValueError("US_WORKLOAD_OWNER_MISMATCH")
    if workload.enabled is not True:
        raise ValueError("US_WORKLOAD_DISABLED")
    if tuple(workload.slots) != US_MARKET_SLOTS:
        raise ValueError("US_WORKLOAD_SLOTS_MISMATCH")
    return workload


def select_us_workload(catalog: RuntimeCatalog | None = None) -> WorkloadDefinition:
    """Return the one enabled, canonically registered US workload.

    The returned object comes from the loaded catalog.  No workload or module
    definition is synthesized by this wrapper.
    """

    source = load_workload_catalog() if catalog is None else catalog
    return _registered_us_workload(source)


def select_us_catalog(catalog: RuntimeCatalog | None = None) -> RuntimeCatalog:
    """Create an in-memory catalog view containing only the US workload."""

    source = load_workload_catalog() if catalog is None else catalog
    workload = _registered_us_workload(source)
    return replace(source, workloads=(workload,))


# A descriptive alias keeps callers from mistaking this for a persisted
# catalog or a replacement producer.
us_only_catalog = select_us_catalog


def _request_for_slot(
    *,
    business_date: str,
    slot: str,
    calendar: Any = None,
) -> DispatchRequest:
    if calendar is None:
        dates = compute_dates(business_date=business_date, slot=slot)
    else:
        dates = compute_dates(
            business_date=business_date,
            slot=slot,
            calendar=calendar,
        )
    return DispatchRequest(
        scheduled_date=dates["scheduled_date"],
        business_date=dates["business_date"],
        target_date=dates["target_date"],
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _timeout(value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("TIMEOUT_INVALID") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("TIMEOUT_INVALID")
    return parsed


def run_us_market_slot(
    *,
    data_root: Path | str,
    ledger_root: Path | str,
    slot: str,
    business_date: str,
    timeout_seconds: float = 600.0,
    dry_run: bool = False,
    calendar: Any = None,
    catalog: RuntimeCatalog | None = None,
    executor: Callable[..., Any] | None = None,
    ledger: ExecutionLedger | None = None,
) -> dict[str, Any]:
    """Run one US-only dispatch using the existing V4 runtime components.

    ``executor`` and ``ledger`` are optional seams for isolated tests.  Normal
    callers leave them unset so the fixed registry and the supplied V4 ledger
    root are used.  A dry run is delegated to ``dispatch_due``; its existing
    dry-run namespace keeps claims and receipts out of the authoritative root.
    """

    selected_slot = _validate_slot(slot)
    timeout = _timeout(timeout_seconds)
    request = _request_for_slot(
        business_date=business_date,
        slot=selected_slot,
        calendar=calendar,
    )
    selected_catalog = select_us_catalog(catalog)
    data_path = Path(data_root)
    ledger_path = Path(ledger_root)
    dispatch_executor = executor
    if dispatch_executor is None:
        dispatch_executor = FixedExecutorRegistry(
            data_root=data_path,
            timeout_seconds=timeout,
            repo_root=Path(__file__).resolve().parents[1],
        )
    dispatch_ledger = ledger if ledger is not None else ExecutionLedger(ledger_path)
    receipt = dispatch_due(
        request,
        selected_catalog,
        dispatch_executor,
        ledger=dispatch_ledger,
        dry_run=bool(dry_run),
    )
    payload = receipt.to_dict()
    payload.update(
        {
            "schema_version": RESULT_SCHEMA,
            "dispatch_schema_version": receipt.schema_version,
            "owner_id": US_MARKET_OWNER_ID,
            "workload_id": US_MARKET_WORKLOAD_ID,
            "dry_run": bool(dry_run),
        }
    )
    return payload


def _failure_payload(
    *, slot: str, business_date: str | None, reason: str, dry_run: bool
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "dispatch_schema_version": None,
        "status": "FAILED",
        "mode": DispatchMode.LIVE.value,
        "slot": slot,
        "business_date": business_date,
        "scheduled_date": business_date,
        "target_date": business_date,
        "selected_workload_ids": [],
        "started_workload_ids": [],
        "workload_results": [],
        "receipt_path": "",
        "reason": reason,
        "owner_id": US_MARKET_OWNER_ID,
        "workload_id": US_MARKET_WORKLOAD_ID,
        "dry_run": bool(dry_run),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the registered V4 US market workload for one Shanghai slot"
    )
    parser.add_argument(
        "--slot",
        help="Shanghai HHMM; only 0415, 0515, 2100, and 2200 are accepted (default: current Shanghai HHMM)",
    )
    parser.add_argument("--date", help="Shanghai business date YYYYMMDD (default: today Shanghai)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(SHANGHAI)
    slot = args.slot or now.strftime("%H%M")
    business_date = args.date or now.strftime("%Y%m%d")
    try:
        result = run_us_market_slot(
            data_root=args.data_root,
            ledger_root=args.ledger_root,
            slot=slot,
            business_date=business_date,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )
    except Exception as error:  # CLI boundary must fail closed and emit JSON.
        reason = f"{type(error).__name__}: {error}"
        print(f"US market slot failed: {reason}", file=sys.stderr)
        result = _failure_payload(
            slot=slot,
            business_date=business_date,
            reason=reason,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in ZERO_EXIT_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RESULT_SCHEMA",
    "SHANGHAI",
    "US_MARKET_OWNER_ID",
    "US_MARKET_SLOT_SET",
    "US_MARKET_SLOTS",
    "US_MARKET_WORKLOAD_ID",
    "ZERO_EXIT_STATUSES",
    "main",
    "run_us_market_slot",
    "select_us_catalog",
    "select_us_workload",
    "us_only_catalog",
]
