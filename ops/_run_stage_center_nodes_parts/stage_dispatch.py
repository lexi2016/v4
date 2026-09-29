"""ops.run_stage_center_nodes: stage_dispatch (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __dispatch_stage_body(_v4_scope, /, config, trade_date, stage_id, evaluated_at, *, mode, runner, precaptures):
    """Run exactly one stage under the runner's existing per-stage lock."""

    if stage_id not in _v4_global(_v4_scope, 'STAGE_BY_ID'):
        raise _v4_global(_v4_scope, 'ValueError')(f"unknown stage node {stage_id!r}")
    gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets)
    if gate["status"] != "ELIGIBLE":
        return {**gate, "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode}
    runner = runner or _v4_global(_v4_scope, '_build_runner')(config)
    max_attempts = _v4_global(_v4_scope, '_config_int')(config, "node_max_attempts", _v4_global(_v4_scope, 'DEFAULT_MAX_ATTEMPTS'))
    retry_backoff = _v4_global(_v4_scope, '_config_float')(
        config, "node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS')
    )
    receipt = _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id)
    attempt_count = _v4_global(_v4_scope, '_node_attempt_count')(receipt)
    existing_status = _v4_global(_v4_scope, 'str')((receipt or {}).get("status") or "")
    # The inner runner may replace receipt.json before it exits. This immutable
    # reservation survives that write and prevents a crash from reopening retries.
    rearm_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / "dependency_rearm.json"
    if rearm_marker.exists() and not _v4_global(_v4_scope, '_stage_settled')(receipt):
        attempt_count = _v4_global(_v4_scope, 'max')(attempt_count, max_attempts + 1)
        existing_status = "CANNOT_CONFIRM"
    if _v4_global(_v4_scope, '_stage_settled')(receipt) and existing_status not in _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        return {
            "status": "SKIPPED_ALREADY_SETTLED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "node_outcome": (receipt or {}).get("node_outcome", "SETTLED"),
            "node_attempt_count": attempt_count,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    rearm = None
    if existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        if attempt_count >= max_attempts:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
        if attempt_count >= max_attempts and rearm is None:
            previous = receipt or {}
            return {
                "status": "SKIPPED_RETRY_EXHAUSTED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT_EXHAUSTED",
                "node_attempt_count": attempt_count,
                "retry_exhausted": True,
                "first_failed_layer": (
                    previous.get("first_failed_layer")
                    or previous.get("blocked_layer")
                    or "STAGE_RETRY_BUDGET_EXHAUSTED"
                ),
                "error": previous.get("error"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        if rearm is None and not _v4_global(_v4_scope, '_retry_is_due')(
            receipt,
            _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
            retry_backoff_seconds=retry_backoff,
        ):
            return {
                "status": "SKIPPED_RETRY_BACKOFF",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT",
                "node_attempt_count": attempt_count,
                "retry_after": (receipt or {}).get("retry_after"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }

    from stage_center.runner import SlotLock, _slot_lock_path

    decision = _v4_global(_v4_scope, 'next')(
        item
        for item in runner.due_decisions(
            trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
        )
        if item.stage_id == stage_id
    )
    if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY"}:
        return {
            "status": decision.status,
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return {
            "status": "SKIPPED_SLOT_LOCKED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    try:
        _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        # Recheck after acquiring the original lock; never overwrite a newer run.
        if _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id) != receipt:
            return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                    "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
        if rearm is not None:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
            if rearm is None:
                return {"status": "SKIPPED_DEPENDENCY_NOT_READY", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            rearm_marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                with rearm_marker.open("x", encoding="utf-8") as stream:
                    _v4_global(_v4_scope, 'json').dump({"schema_version": "stage_center.dependency_rearm.v1",
                               "trade_date": trade_date, "stage_id": stage_id,
                               **rearm, **_v4_global(_v4_scope, '_safe_flags')()}, stream, sort_keys=True)
                    stream.flush()
                    _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            except _v4_global(_v4_scope, 'FileExistsError'):
                return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            runner._write_receipt({**(receipt or {}), **rearm}, trade_date, stage_id)
        # Stage-8 pre-capture is scheduled at 15:50 and, when a launch lands
        # exactly on 15:55:00, may be retried once more before the 15:55:05
        # consumer cutoff.  Never invoke it after the immutable window.
        captured = _v4_global(_v4_scope, 'list')(precaptures or ())
        attempt_count += 1
        _v4_global(_v4_scope, '_deadline').due(
            decision.scheduled_at,
            trade_date=trade_date,
            stage_id=stage_id,
            due_status=decision.status,
            dispatch_mode=mode,
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        # Diagnostics only; slot lock, attempt budget and cutoff policy are unchanged.
        from stage_center.attempt_evidence import capture_attempt
        with capture_attempt(
            runner._receipt_path(trade_date, stage_id).parent,
            trade_date=trade_date, stage_id=stage_id, attempt_number=attempt_count,
            evaluated_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
            due_status=decision.status,
        ) as attempt_journal:
            result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            attempt_journal.finish(result)
        result["attempt_diagnostic"] = attempt_journal.summary()
        _v4_global(_v4_scope, '_deadline').event("BUSINESS_RETURN", status=result.get("status"))
        result.update(
            {
                "node_id": stage_id,
                "dispatch_mode": mode,
                "node_attempt_count": attempt_count,
                "pre_captures": captured,
            }
        )
        # Preserve consumed re-arm metadata across both success and failure.
        result.update({k: v for k, v in (receipt or {}).items()
                       if k.startswith("dependency_rearm_")})
        if rearm is not None:
            result.update(rearm)
        status = _v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM")
        if status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            # A partial status without a committed write is not a valid
            # settled partial.  Reclassify it into the bounded retry lane.
            result["status"] = status = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        outcome = _v4_global(_v4_scope, '_node_outcome')(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = _v4_global(_v4_scope, 'bool')(
            outcome == "TRANSIENT" and attempt_count >= max_attempts
        )
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                + _v4_global(_v4_scope, 'timedelta')(seconds=retry_backoff)
            ).isoformat()
        else:
            result.pop("retry_after", None)
        # _record_dispatch_metadata is the existing receipt writer and keeps
        # the base runner's schema and safety flags.  The final write adds the
        # node cap metadata atomically through the same per-stage lock.
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _v4_global(_v4_scope, '_deadline').complete_receipt(
            runner._receipt_path(trade_date, stage_id),
            persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        return persisted
    finally:
        lock.release()
