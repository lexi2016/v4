"""stage_center.runner: tick_planning (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageCenterRunner__backfill_runner_body(_v4_scope, /, self, run_id):
    if not _v4_global(_v4_scope, 're').fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise _v4_global(_v4_scope, 'RunnerError')("historical backfill run id is unsafe")
    base = self.config
    scoped = _v4_global(_v4_scope, 'replace')(
        base,
        raw_root=base.raw_root / "backfill" / run_id,
        selection_root=base.selection_root / "backfill" / run_id,
        receipt_root=base.receipt_root / "backfill" / run_id,
        backfill_run_id=run_id,
    )
    return _v4_global(_v4_scope, 'StageCenterRunner')(scoped, collectors=self.collectors)


def _StageCenterRunner_tick_body(_v4_scope, /, self, trade_date, evaluated_at, *, stage_id, historical_backfill, historical_markets, _skip_precapture):
    if historical_markets is not None:
        if not historical_backfill:
            raise _v4_global(_v4_scope, 'RunnerError')(
                "historical market allowlist requires historical_backfill"
            )
        if stage_id is None:
            raise _v4_global(_v4_scope, 'RunnerError')(
                "historical market allowlist requires one explicit stage"
            )
        # Validate before Stage-8 pre-capture or any other producer can run.
        _v4_global(_v4_scope, '_resolve_stage_market_scope')(
            stage_id,
            trade_date,
            historical_backfill=historical_backfill,
            historical_markets=historical_markets,
        )
    precaptures = (
        []
        if _skip_precapture
        else self._prepare_hk_active_snapshots(
            trade_date,
            evaluated_at,
            stage_id=stage_id,
            historical_backfill=historical_backfill,
        )
    )
    decisions = self.due_decisions(trade_date, evaluated_at, historical_backfill=historical_backfill)
    if stage_id is None:
        due = [decision for decision in decisions if decision.status in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}]
        if not due:
            return {"status": decisions[0].status if decisions else "CANNOT_CONFIRM", "trade_date": trade_date, "stages": [decision.status for decision in decisions], "pre_captures": precaptures, **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
        results = [
            self.tick(
                trade_date,
                evaluated_at,
                stage_id=decision.stage_id,
                historical_backfill=historical_backfill,
                historical_markets=historical_markets,
                _skip_precapture=True,
            )
            for decision in due
        ]
        return {"status": "TICK_COMPLETE", "trade_date": trade_date, "stages": results, "pre_captures": precaptures, **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    decision = _v4_global(_v4_scope, 'next')((item for item in decisions if item.stage_id == stage_id), None)
    if decision is None:
        decision = _v4_global(_v4_scope, 'evaluate_due')(stage_id, trade_date, evaluated_at, historical_backfill=historical_backfill)
    if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
        if historical_backfill:
            scoped = self._backfill_runner(_v4_global(_v4_scope, 'uuid4')().hex)
            return scoped._write_receipt(
                {
                    "status": decision.status,
                    "due_status": decision.status,
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "write_performed": False,
                },
                trade_date,
                stage_id,
            )
        return self._write_receipt({"status": decision.status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "pre_captures": precaptures, "write_performed": False}, trade_date, stage_id)
    runner = self
    backfill_run_id: str | None = None
    if historical_backfill:
        backfill_run_id = _v4_global(_v4_scope, 'uuid4')().hex
        runner = self._backfill_runner(backfill_run_id)
    lock = _v4_global(_v4_scope, 'SlotLock')(_v4_global(_v4_scope, '_slot_lock_path')(runner.config, trade_date, stage_id))
    if not lock.acquire():
        return runner._write_receipt({"status": "SKIPPED_SLOT_LOCKED", "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "write_performed": False}, trade_date, stage_id)
    try:
        return runner._run_one(
            decision,
            historical_backfill=historical_backfill,
            backfill_run_id=backfill_run_id,
            historical_markets=historical_markets,
        )
    finally:
        lock.release()
