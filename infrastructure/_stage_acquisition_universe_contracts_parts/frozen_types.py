"""infrastructure.stage_acquisition_universe_contracts: frozen_types (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StrictAPreselectionSnapshot_as_projection_body(_v4_scope, /, self):
    """Expose the historical projection shape without losing source data."""

    pools = [_v4_global(_v4_scope, '_thaw')(pool.artifact) for pool in self.pools]
    rows = [_v4_global(_v4_scope, '_thaw')(row) for row in self.a_all_pool_rows]
    return {
        "ok": self.ready,
        "trade_date": self.trade_date,
        "data_status": "READY_WITH_ROWS" if self.ready else "CANNOT_CONFIRM",
        "status": "READY_WITH_ROWS" if self.ready else "CANNOT_CONFIRM",
        "codes": _v4_global(_v4_scope, 'list')(self.codes),
        "row_count": _v4_global(_v4_scope, 'len')(self.codes),
        "pools": pools,
        "a_all_pool_rows": rows,
        "a_all_pool_row_count": _v4_global(_v4_scope, 'len')(rows),
        "code_sources": {
            code: _v4_global(_v4_scope, 'list')(pool_ids) for code, pool_ids in self.code_sources.items()
        },
        "cannot_confirm": _v4_global(_v4_scope, 'list')(self.diagnostic_reasons) + _v4_global(_v4_scope, 'list')(self.blocking_reasons),
        "blocking_reasons": _v4_global(_v4_scope, 'list')(self.blocking_reasons),
        "diagnostic_reasons": _v4_global(_v4_scope, 'list')(self.diagnostic_reasons),
        "pool_diagnostics": {
            pool_id: _v4_global(_v4_scope, 'list')(reasons)
            for pool_id, reasons in self.pool_diagnostics.items()
        },
        "pool_contribution_counts": _v4_global(_v4_scope, 'dict')(self.pool_contribution_counts),
        "known_pool_ids": _v4_global(_v4_scope, 'list')(self.known_pool_ids),
        "available_pool_ids": _v4_global(_v4_scope, 'list')(self.pool_ids),
        "policy_notes": _v4_global(_v4_scope, 'list')(self.policy_notes),
        "stage_selection_eligible": self.stage_selection_eligible,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "strict_snapshot": True,
    }
