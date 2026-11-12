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
        try:
            binding = _v4_global(_v4_scope, '_build_hk_stage_binding')(
                self.config.hk_d1_root, trade_date,
                preselection_source_root=self.config.preselection_source_root,
            )
        except (OSError, ValueError, _v4_global(_v4_scope, 'RunnerError')):
            store = self.config.hk_snapshot_shared_store_root
            if store is None:
                raise
            # Only this capture loader can use the already verified same-target
            # shared producer. Selection still requires its original local binding.
            from datetime import datetime, timedelta
            from domains.preselection_materializer import build_shared_hk_0_2_pool
            states = _v4_global(_v4_scope, 'resolve_market_states')
            open_states = {_v4_global(_v4_scope, 'TradingDayState').FULL_TRADING_DAY,
                           _v4_global(_v4_scope, 'TradingDayState').HALF_TRADING_DAY_AM}
            if states(trade_date)["hk_connect"] not in open_states:
                raise ValueError("capture-only shared membership requires an open exact Connect target")
            cursor = datetime.strptime(trade_date, "%Y%m%d")
            signal_date = None
            for _ in range(45):
                cursor -= timedelta(days=1)
                prior = states(cursor.strftime("%Y%m%d"))
                if any(prior[k] is _v4_global(_v4_scope, 'TradingDayState').UNKNOWN for k in ("hk_securities", "hk_connect")):
                    raise ValueError("capture-only shared signal calendar CANNOT_CONFIRM")
                if prior["hk_securities"] in open_states or prior["hk_connect"] in open_states:
                    if not all(prior[k] in open_states for k in ("hk_securities", "hk_connect")):
                        raise ValueError("capture-only shared split signal dates unsupported")
                    signal_date = cursor.strftime("%Y%m%d")
                    break
            if signal_date is None:
                raise ValueError("capture-only shared signal date unavailable")
            payload = build_shared_hk_0_2_pool(store, trade_date=trade_date,
                signal_date=signal_date, shared_package_root=self.config.shared_data_root)
            if payload.get("status") != "STRICT_0_2_READY" or len(payload.get("rows") or ()) != 100:
                raise ValueError("capture-only shared exact membership is not strict Top100")
            digest = payload["source_sha256"]
            binding = _v4_global(_v4_scope, 'StageUniverseBinding').ready(
                market="HK_CONNECT", trade_date=trade_date, role="HK_CAPTURE_ONLY_SHARED_VERIFIED_D1",
                codes=tuple(row["symbol"] for row in payload["rows"]), sha256=digest,
                source_run_id=payload["source_run_id"], evidence=(
                    "hk_snapshot_membership_role=CAPTURE_ONLY_SHARED_VERIFIED_D1",
                    f"hk_d1_json={store / payload['source_path']}",
                    f"hk_d1_source_trade_date={trade_date}", f"hk_d1_source_signal_date={signal_date}",
                    f"hk_d1_sha256={digest}", f"hk_d1_source_run_id={payload['source_run_id']}",
                ))
        loaded_binding = binding
        return (
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '_evidence_value')(binding.evidence, "hk_d1_json") or self.config.hk_d1_root),
            binding.codes,
            binding.sha256,
        )

    from stage_center.hk_stage8 import prepare_due_snapshot, prepare_hk_active_snapshot

    def snapshot_preparer(*args, **kwargs):
        kwargs["capture_source_evidence"] = list(loaded_binding.evidence) if loaded_binding is not None else []
        kwargs["capture_only"] = loaded_binding is not None and loaded_binding.role == "HK_CAPTURE_ONLY_SHARED_VERIFIED_D1"
        return prepare_hk_active_snapshot(*args, **kwargs)

    results = prepare_due_snapshot(
        self.config,
        trade_date,
        evaluated_at,
        stage_id=stage_id,
        historical_backfill=historical_backfill,
        universe_loader=universe_loader,
        snapshot_preparer=snapshot_preparer,
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
    runner_error = _v4_global(_v4_scope, 'RunnerError')
    if "RESEARCH_ONLY" in payload and payload["RESEARCH_ONLY"] is not True:
        raise runner_error("runner receipt RESEARCH_ONLY contract conflict")
    result = {"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center", **_v4_global(_v4_scope, '_deadline').before_receipt(payload), **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    from stage_center.contracts import HK_SNAPSHOT_SCHEDULE
    if stage_id in HK_SNAPSHOT_SCHEDULE and not self.config.backfill_run_id:
        from stage_center.hk_stage8.snapshot import hk_snapshot_capture_receipt
        try:
            result["hk_snapshot_capture"] = hk_snapshot_capture_receipt(
                self.config.raw_root, trade_date=trade_date, stage_id=stage_id)
        except (OSError, ValueError, TypeError) as error:
            result["hk_snapshot_capture"] = {"status": "CANNOT_CONFIRM", "error": f"{type(error).__name__}:{error}",
                                              "authorizes_selection": False}
    scope = getattr(self, "_execution_scope", None)
    if scope is not None:
        result = scope.merge(result, trade_date, stage_id)
    if any(result.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise runner_error("runner receipt safety contract conflict")
    if "RESEARCH_ONLY" not in result:
        result["RESEARCH_ONLY"] = True
    elif result["RESEARCH_ONLY"] is not True:
        raise runner_error("runner receipt RESEARCH_ONLY contract conflict")
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
    from stage_center.receipt_lineage import bind_owner_receipt
    result = bind_owner_receipt(result, receipt_root=self.config.receipt_root,
                                selection_root=self.config.selection_root, trade_date=trade_date, stage_id=stage_id)
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
