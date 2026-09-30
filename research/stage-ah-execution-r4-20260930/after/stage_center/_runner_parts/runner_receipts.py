"""stage_center.runner: runner_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageCenterRunner__prepare_hk_active_snapshots_body(_v4_scope, /, self, trade_date, evaluated_at, *, stage_id, historical_backfill):
    """Delegate the Stage-8-only 15:50 immutable pre-capture.

        The universe loader keeps the existing V4 verified-pool validator at
        the boundary.  On HK-open/Connect-closed days it may use the newest
        earlier verified D-1 membership, preserving the original source date
        and SHA; quotes remain exact to the observation date.
        """

    loaded_binding: StageUniverseBinding | None = None

    def universe_loader() -> tuple[Path, tuple[str, ...], str]:
        nonlocal loaded_binding
        if self.config.hk_d1_root is None:
            raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 Top100 root is required for Stage 8 pre-capture")
        binding = _v4_global(_v4_scope, '_build_hk_stage_binding')(
            self.config.hk_d1_root,
            trade_date,
            preselection_source_root=self.config.preselection_source_root,
        )
        loaded_binding = binding
        return (
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '_evidence_value')(binding.evidence, "hk_d1_json") or self.config.hk_d1_root),
            binding.codes,
            binding.sha256,
        )

    from stage_center.hk_stage8 import prepare_due_snapshot, prepare_hk_active_snapshot

    results = prepare_due_snapshot(
        self.config,
        trade_date,
        evaluated_at,
        stage_id=stage_id,
        historical_backfill=historical_backfill,
        universe_loader=universe_loader,
        snapshot_preparer=prepare_hk_active_snapshot,
    )
    if loaded_binding is not None:
        source_trade_date = _v4_global(_v4_scope, '_evidence_value')(
            loaded_binding.evidence, "hk_d1_source_trade_date"
        ) or trade_date
        source_signal_date = _v4_global(_v4_scope, '_evidence_value')(
            loaded_binding.evidence, "hk_d1_source_signal_date"
        )
        for item in results:
            item.update({
                "hk_d1_source_trade_date": source_trade_date,
                "hk_d1_source_signal_date": source_signal_date,
                "hk_d1_source_sha256": loaded_binding.sha256,
                "hk_observation_trade_date": trade_date,
                "source_evidence": _v4_global(_v4_scope, 'list')(loaded_binding.evidence),
            })
    return results


def _StageCenterRunner__write_receipt_body(_v4_scope, /, self, payload, trade_date, stage_id):
    result = {"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center", **_v4_global(_v4_scope, '_deadline').before_receipt(payload), **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    scope = getattr(self, "_execution_scope", None)
    if scope is not None:
        result = scope.merge(result, trade_date, stage_id)
    if self.config.backfill_run_id:
        result.update(
            {
                "mode": "BACKFILL",
                "backfill_run_id": self.config.backfill_run_id,
                "latest_updated": False,
                "current_updated": False,
                "namespace": {
                    "raw_root": _v4_global(_v4_scope, 'str')(self.config.raw_root),
                    "selection_root": _v4_global(_v4_scope, 'str')(self.config.selection_root),
                    "receipt_root": _v4_global(_v4_scope, 'str')(self.config.receipt_root),
                },
            }
        )
    receipt_path = self._receipt_path(trade_date, stage_id)
    _v4_global(_v4_scope, '_atomic_json')(receipt_path, result)
    _v4_global(_v4_scope, '_deadline').receipt_written(receipt_path, result)
    return result


class _ExecutionScope:
    """Internal scope on a copied original runner, never a second producer.

    The dispatcher owns the original slot lock and budget. All original inner
    receipt writes and outer deadline rewrites share this merge contract.
    """

    def __init__(self, markets, prior, attempt_count, origin):
        from copy import deepcopy
        self.markets = tuple(markets)
        self.prior = deepcopy(prior)
        self.attempt_count = attempt_count
        self.origin = origin

    def merge(self, payload, trade_date, stage_id):
        from copy import deepcopy
        if (trade_date != self.prior["trade_date"] or stage_id != self.prior["stage_id"]):
            raise ValueError("recovery receipt slot changed")
        result = {**deepcopy(self.prior), **deepcopy(payload)}
        old_markets = self.prior.get("markets") or {}
        new_markets = payload.get("markets") or {}
        # Never take a sibling from an error payload, an empty projection, or
        # a fresh candidate binding. Preserve its original complete object.
        result["markets"] = {
            **deepcopy(old_markets),
            **{m: deepcopy(new_markets[m]) for m in self.markets if m in new_markets},
        }
        result["node_attempt_count"] = self.attempt_count
        result["execution_pending"] = payload.get("execution_pending", False)
        result["execution_markets"] = list(self.markets)
        result["execution_origin"] = self.origin
        result["execution_status"] = payload.get("execution_status", payload.get("status", "CANNOT_CONFIRM"))
        for key, value in self.prior.items():
            if key.startswith(("repair_recovery_", "dependency_rearm_")):
                result[key] = deepcopy(value)
        if "A_SHARE" not in self.markets and "A_SHARE" in old_markets:
            for key in ("candidate_current_sha256", "candidate_run_id"):
                if key in self.prior:
                    result[key] = deepcopy(self.prior[key])
        # Successful execution is not automatically a successful whole stage.
        # Real failures retain their original status/reason and retry semantics.
        if result.get("status") in {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
            states = {str(lane.get("selection_status", lane.get("status", "CANNOT_CONFIRM")))
                      for lane in result["markets"].values()}
            if not states <= {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
                result["status"] = "PARTIAL_WITH_ROWS"
        return result


def scoped_recovery_runner(runner, *, markets, prior_receipt, attempt_count, origin):
    """Bind a per-call market scope to the same runner, config and stores.

    No new roots, collectors, selectors or retry budgets are introduced. The
    caller must already own the slot lock; this function does not authorize a
    run. The original receipt is archived byte-for-byte before its reservation.
    """
    from copy import copy
    import hashlib
    import json
    from infrastructure.owned_io import SafeRoot

    if tuple(markets) not in {("A_SHARE",), ("HK_CONNECT",)}:
        raise ValueError("recovery requires one existing market lane")
    path = runner._receipt_path(prior_receipt["trade_date"], prior_receipt["stage_id"])
    io = SafeRoot(path.parent)
    raw = io.read_bytes(path.name)
    if json.loads(raw) != prior_receipt:
        raise ValueError("recovery receipt changed before scoping")
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"attempt_evidence/preserved-{digest}/PRIOR_RECEIPT.json"
    try:
        io.write_bytes(relative, raw, require_absent=True)
    except FileExistsError:
        if io.read_bytes(relative) != raw:
            raise ValueError("preserved recovery receipt conflict")
    scoped = copy(runner)
    scoped._execution_scope = _ExecutionScope(markets, prior_receipt, attempt_count, origin)
    return scoped
