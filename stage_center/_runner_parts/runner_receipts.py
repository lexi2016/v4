"""stage_center.runner: runner_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageCenterRunner__prepare_hk_active_snapshots_body(_v4_scope, /, self, trade_date, evaluated_at, *, stage_id, historical_backfill):
    """Prepare the exact stage-scoped HK snapshot inside its frozen window.

    The universe loader uses the existing V4 verified D1-pool validator.
    Membership source date and SHA remain separate from exact observation-date
    quote rows.
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
