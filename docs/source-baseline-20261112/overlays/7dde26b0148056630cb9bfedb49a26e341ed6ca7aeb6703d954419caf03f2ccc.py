"""Retry one failed stage market using the existing lock, budget and stores."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping


def failed_market_lanes(receipt: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not receipt or not isinstance(receipt.get("markets"), Mapping):
        return ()
    return tuple(market for market, lane in receipt["markets"].items()
                 if market in {"A_SHARE", "HK_CONNECT"}
                 and isinstance(lane, Mapping)
                 and str(lane.get("selection_status", lane.get("status", "")))
                 in {"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"})


def dispatch_partial_market_retry(api, config, trade_date, stage_id, evaluated_at,
                                  *, mode, runner, receipt):
    """Return None outside this repair; late work stays on the afterfact route.

    Committed siblings are never passed to a collector or selector. The original
    scoped runner archives the exact prior receipt and merges the full sibling
    object on every inner/outer write, including unexpected failures.
    """
    failed = failed_market_lanes(receipt)
    if not receipt or receipt.get("status") not in {"PARTIAL_WITH_ROWS", "CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"} or len(failed) != 1:
        return None
    siblings = set((receipt.get("markets") or {})) - set(failed)
    if not siblings:
        return None
    if any(str(receipt["markets"][m].get("selection_status", receipt["markets"][m].get("status", "")))
           not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "NOOP_ALREADY_VERIFIED"}
           for m in siblings):
        return None
    flags = api["_safe_flags"]()
    count = api["_node_attempt_count"](receipt)
    base = dict(trade_date=trade_date, stage_id=stage_id, node_id=stage_id,
                dispatch_mode=mode, node_attempt_count=count,
                retry_markets=list(failed), write_performed=False, **flags)
    budget = api["_config_int"](config, "node_max_attempts", api["DEFAULT_MAX_ATTEMPTS"])
    if count >= budget:
        return {**base, "status": "SKIPPED_RETRY_EXHAUSTED", "retry_exhausted": True,
                "node_outcome": "TRANSIENT_EXHAUSTED"}
    delay = api["_config_float"](config, "node_retry_backoff_seconds", api["DEFAULT_RETRY_BACKOFF_SECONDS"])
    timing_receipt = receipt
    if (not receipt.get("retry_after") and not receipt.get("attempted_at")
            and receipt.get("record_time_source") == "OWNER_WRITE_CLOCK_UTC"):
        # Old SETTLED_PARTIAL omitted retry metadata. Its owner write clock is
        # an observed anchor; filesystem mtime and stage cutoff are not.
        timing_receipt = {**receipt, "attempted_at": receipt.get("recorded_at")}
    if not api["_retry_is_due"](timing_receipt, evaluated_at, retry_backoff_seconds=delay):
        return {**base, "status": "SKIPPED_RETRY_BACKOFF", "node_outcome": "TRANSIENT"}
    decision = next((d for d in runner.due_decisions(trade_date, evaluated_at,
                    historical_backfill=False) if d.stage_id == stage_id), None)
    if decision is None or decision.status != "DUE":
        return {**base, "status": "SKIPPED_FORMAL_RETRY_WINDOW_CLOSED",
                "node_outcome": "TRANSIENT", "afterfact_required": True,
                "recovery_status": "SEALED_RAW_OR_AFTERFACT_WATCH_ONLY"}
    from stage_center.runner import SlotLock, _slot_lock_path
    from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    if not lock.acquire():
        return {**base, "status": "SKIPPED_SLOT_LOCKED"}
    try:
        if api["_read_receipt"](config, trade_date, stage_id) != receipt:
            return {**base, "status": "SKIPPED_RECEIPT_CHANGED"}
        scoped = scoped_recovery_runner(runner, markets=failed, prior_receipt=receipt,
                    attempt_count=count + 1, origin="FAILED_MARKET_ORIGINAL_BUDGET_RETRY")
        # Reserve before invoking a provider: crashes consume this attempt.
        scoped._write_receipt({**receipt, "status": "CANNOT_CONFIRM",
            "node_outcome": "TRANSIENT", "execution_pending": True,
            "node_attempt_count": count + 1, "write_performed": False}, trade_date, stage_id)
        from stage_center import end_to_end_deadline as deadline
        deadline.due(decision.scheduled_at, trade_date=trade_date, stage_id=stage_id,
                     due_status=decision.status, dispatch_mode=mode)
        try:
            result = dict(scoped._run_one(decision))
        except Exception as error:
            result = scoped._write_receipt({"status": "CANNOT_CONFIRM",
                "error": f"{type(error).__name__}:{error}",
                "markets": {failed[0]: {"selection_status": "CANNOT_CONFIRM",
                    "selected_rows": 0, "cannot_confirm": [f"{type(error).__name__}:{error}"]}},
                "write_performed": False}, trade_date, stage_id)
        result.update(node_attempt_count=count + 1, dispatch_mode=mode, node_id=stage_id)
        transient = bool(failed_market_lanes(result))
        result["node_outcome"] = "TRANSIENT" if transient else api["_node_outcome"](str(result.get("status")), result)
        result["retry_exhausted"] = transient and count + 1 >= budget
        if transient and not result["retry_exhausted"]:
            result["retry_after"] = (evaluated_at + timedelta(seconds=delay)).isoformat()
        else:
            result.pop("retry_after", None)
        persisted = scoped._write_receipt(result, trade_date, stage_id)
        return deadline.complete_receipt(scoped._receipt_path(trade_date, stage_id), persisted,
                    rewrite=lambda failed: scoped._write_receipt(failed, trade_date, stage_id))
    finally:
        lock.release()
