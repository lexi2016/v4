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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import DispatchMode, DispatchRequest, RuntimeCatalog, WorkloadDefinition
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from contracts.trading_calendar import load_market_calendar, next_session
from ops.run_scheduled_slot import compute_dates


SHANGHAI = ZoneInfo("Asia/Shanghai")
US_MARKET_WORKLOAD_ID = "us_market_digest"
US_MARKET_OWNER_ID = "v4_dispatcher.us_market_digest"
US_MARKET_SLOTS: tuple[str, ...] = ("0415", "0515", "2100", "2200")
US_MARKET_SLOT_SET = frozenset(US_MARKET_SLOTS)
# The fixed slots are seasonal.  Only these inactive slots can safely host a
# late POST_CLOSE retry without taking over the other season's PRE_OPEN event.
US_MARKET_CLOSE_RETRY_SLOTS = {"0515": "0415", "2100": "0515"}
US_MARKET_RETRYABLE_FAILURES = frozenset(
    {"EXTERNAL_SOURCE", "NETWORK", "UPSTREAM_NOT_READY"}
)
DEFAULT_SLOT_GRACE = timedelta(minutes=15)
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


def _default_slot_for_time(now: datetime) -> str:
    """Resolve only a recently elapsed planned slot on the Shanghai date.

    Default launches may be delayed by at most fifteen minutes.  Explicit
    ``--slot`` input continues through the original strict slot validator.
    """

    if now.tzinfo is None:
        raise ValueError("US_DEFAULT_SLOT_TIMEZONE_REQUIRED")
    local = now.astimezone(SHANGHAI)
    elapsed: list[tuple[datetime, str]] = []
    for planned_slot in US_MARKET_SLOTS:
        planned = local.replace(
            hour=int(planned_slot[:2]),
            minute=int(planned_slot[2:]),
            second=0,
            microsecond=0,
        )
        if planned <= local:
            elapsed.append((planned, planned_slot))
    if not elapsed:
        raise ValueError("US_DEFAULT_SLOT_NOT_DUE")
    planned, selected = max(elapsed)
    if local - planned > DEFAULT_SLOT_GRACE:
        raise ValueError("US_DEFAULT_SLOT_WINDOW_EXPIRED")
    return selected


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
    # The US capture slot's Shanghai date is not the next HK selection date.
    # Keep scheduled/business dates for dispatch identity, but resolve the
    # selection target through the existing authoritative HK securities calendar.
    if slot in US_MARKET_SLOT_SET:
        hk_calendar = calendar or load_market_calendar()
        from ops.us_market_digest import resolve_capture_for_shanghai_slot

        try:
            capture = resolve_capture_for_shanghai_slot(business_date, slot)
        except ValueError as error:
            # Non-capture slots historically retain their strict Shanghai-date
            # target semantics. Other failures stay visible instead of being
            # hidden by a Shanghai-date fallback.
            if str(error) != "US_CAPTURE_SLOT_NOT_DUE":
                raise
            capture = None
        if capture is not None and capture["capture_phase"] == "POST_CLOSE":
            hk_anchor = capture["us_session_date"]
        else:
            hk_anchor = business_date
        dates["target_date"] = next_session(
            hk_calendar, hk_anchor, market="hk_securities"
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


def _failed_close_retry_context(
    *, ledger: ExecutionLedger, business_date: str, retry_slot: str
) -> dict[str, str] | None:
    """Return a bounded retry identity only for an exact prior close failure.

    The fallback slot must be inactive in the current season.  Its paired
    primary slot must have a hash-valid, failed POST_CLOSE receipt for the
    same business date and resolved US session.  Any previous use of the
    fallback slot consumes this one scheduled retry opportunity.
    """

    primary_slot = US_MARKET_CLOSE_RETRY_SLOTS.get(retry_slot)
    if primary_slot is None:
        return None

    from ops.us_market_digest import resolve_capture_for_shanghai_slot

    try:
        resolve_capture_for_shanghai_slot(business_date, retry_slot)
    except ValueError as error:
        if str(error) != "US_CAPTURE_SLOT_NOT_DUE":
            return None
    else:
        # A live slot belongs to its normal phase; never replace PRE_OPEN with
        # a close retry just because an earlier close failed.
        return None

    try:
        primary_capture = resolve_capture_for_shanghai_slot(
            business_date, primary_slot
        )
    except ValueError:
        return None
    if primary_capture.get("capture_phase") != "POST_CLOSE":
        return None

    receipts = ledger.list_receipts(business_date, mode="LIVE")
    fallback_receipts = [
        item for item in receipts if str(item.get("slot") or "") == retry_slot
    ]
    if fallback_receipts:
        return None
    primary_receipts = [
        item for item in receipts if str(item.get("slot") or "") == primary_slot
    ]
    if not primary_receipts:
        return None
    chain_valid, _ = ledger.verify_receipt_chain(business_date, mode="LIVE")
    if not chain_valid:
        return None
    failed = primary_receipts[-1]
    if (
        failed.get("status") != "FAILED"
        or failed.get("business_date") != business_date
        or failed.get("scheduled_date") != business_date
        or failed.get("target_date") != business_date
        or failed.get("mode") != "LIVE"
        or failed.get("failure_class") not in US_MARKET_RETRYABLE_FAILURES
        or failed.get("production_allowed") is not False
        or failed.get("buy_gate_updated") is not False
        or failed.get("orders_sent") is not False
        or US_MARKET_WORKLOAD_ID not in (failed.get("selected_workload_ids") or [])
    ):
        return None
    try:
        expected_receipt_path = ledger.receipt_relative(
            _request_for_slot(business_date=business_date, slot=primary_slot),
            run_id=str(failed.get("run_id") or ""),
        )
    except (TypeError, ValueError):
        return None
    if not failed.get("run_id") or failed.get("receipt_path") != expected_receipt_path:
        return None

    workload_results = failed.get("workload_results")
    if not isinstance(workload_results, list):
        return None
    matching_results = [
        row
        for row in workload_results
        if isinstance(row, dict)
        and "ops.us_market_digest" in (row.get("modules") or [])
    ]
    if len(matching_results) != 1:
        return None
    result = matching_results[0]
    if (
        result.get("status") != "FAILED"
        or result.get("failure_class") not in US_MARKET_RETRYABLE_FAILURES
        or result.get("capture_phase") != "POST_CLOSE"
        or result.get("us_session_date") != primary_capture.get("us_session_date")
        or result.get("production_allowed") is not False
        or result.get("buy_gate_updated") is not False
        or result.get("orders_sent") is not False
        or result.get("reason")
        not in {"US_MARKET_CAPTURE_FAILED", "US_MARKET_CAPTURE_NOT_READY"}
    ):
        return None

    return {
        "business_date": business_date,
        "retry_slot": retry_slot,
        "failed_slot": primary_slot,
        "capture_phase": "POST_CLOSE",
        "us_session_date": str(primary_capture["us_session_date"]),
        "failed_run_id": str(failed["run_id"]),
        "failed_receipt_path": expected_receipt_path,
        "failed_ledger_sha256": str(failed.get("ledger_sha256") or ""),
    }


class _RetryAwareExecutor:
    """Use the primary close slot for capture while keeping fallback ledger ID."""

    def __init__(self, executor: Callable[..., Any], context: dict[str, str]) -> None:
        self.executor = executor
        self.context = dict(context)

    def __call__(self, workload: Any, request: Any, decision: Any = None) -> Any:
        if getattr(workload, "workload_id", None) != US_MARKET_WORKLOAD_ID:
            return self.executor(workload, request, decision)
        capture_request = replace(request, slot=self.context["failed_slot"])
        had_context = hasattr(self.executor, "_us_market_retry_context")
        previous_context = getattr(self.executor, "_us_market_retry_context", None)
        try:
            try:
                setattr(self.executor, "_us_market_retry_context", self.context)
            except (AttributeError, TypeError):
                # A wrapper without retry-context support keeps the scheduled
                # fallback identity and therefore follows its normal no-op.
                return self.executor(workload, request, decision)
            result = self.executor(workload, capture_request, decision)
            if isinstance(result, dict):
                result = dict(result)
                result.setdefault("late_post_close_retry", True)
                result.setdefault("retry_of_slot", self.context["failed_slot"])
                result.setdefault("retry_slot", self.context["retry_slot"])
                result.setdefault("retry_failed_run_id", self.context["failed_run_id"])
                result.setdefault(
                    "retry_failed_ledger_sha256",
                    self.context["failed_ledger_sha256"],
                )
                result.setdefault("retry_mode", "AUTOMATIC_LATE_RETRY")
                result.setdefault(
                    "retry_executed_at", result.get("capture_captured_at")
                )
                result.setdefault(
                    "retry_source_session_date", self.context["us_session_date"]
                )
                result.setdefault(
                    "retry_target_trade_date", self.context["business_date"]
                )
                result.setdefault(
                    "retry_capture_origin", result.get("capture_origin")
                )
                result.setdefault(
                    "retry_capture_original_time",
                    result.get("original_time_capture"),
                )
                result.setdefault("retry_capture_late", result.get("late"))
                result.setdefault(
                    "capture_origin_semantics",
                    "Producer origin is independent of timing; late and capture_captured_at record timing.",
                )
            return result
        finally:
            if had_context:
                setattr(self.executor, "_us_market_retry_context", previous_context)
            else:
                try:
                    delattr(self.executor, "_us_market_retry_context")
                except AttributeError:
                    pass


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
    retry_context = (
        None
        if dry_run
        else _failed_close_retry_context(
            ledger=dispatch_ledger,
            business_date=request.business_date,
            retry_slot=selected_slot,
        )
    )
    if retry_context is not None:
        dispatch_executor = _RetryAwareExecutor(dispatch_executor, retry_context)
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
            "close_retry": (
                {
                    "status": "ARMED",
                    **retry_context,
                }
                if retry_context is not None
                else {"status": "NOT_ARMED"}
            ),
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
        help="Shanghai HHMM; only 0415, 0515, 2100, and 2200 are accepted (default: latest elapsed slot, within 15 minutes)",
    )
    parser.add_argument("--date", help="Shanghai business date YYYYMMDD (default: today Shanghai)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(SHANGHAI)
    slot = args.slot if args.slot is not None else now.strftime("%H%M")
    business_date = args.date or now.strftime("%Y%m%d")
    try:
        if args.slot is None:
            slot = _default_slot_for_time(now)
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
