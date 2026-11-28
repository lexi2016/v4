"""Saved manager plan projections used by the unchanged list client."""
from __future__ import annotations

from typing import Any


def list_snapshot(snapshot: Any) -> dict[str, Any]:
    """Keep the public PlanMetadata contract without serializing raw plan histories."""
    context = snapshot.context
    names = ("market", "target_date", "phase", "cutoff", "trigger",
             "source_sessions", "rules_version")
    ctx = {name: getattr(context, name) for name in names}
    ctx["scope_refs"] = {
        "source_cutoff": context.scope_refs.get("source_cutoff"),
    }
    lanes = [
        {
            "lane": lane.lane.value, "state": lane.state.value,
            "coverage": lane.coverage.model_dump(mode="json"),
            "rows_count": len(lane.rows), "gaps": lane.gaps,
        }
        for lane in snapshot.lanes
    ]
    return {
        "RESEARCH_ONLY": snapshot.RESEARCH_ONLY,
        "production_allowed": snapshot.production_allowed,
        "buy_gate_updated": snapshot.buy_gate_updated,
        "orders_sent": snapshot.orders_sent,
        "schema_version": snapshot.schema_version,
        "context": ctx,
        "run_id": snapshot.run_id,
        "input_sha256": snapshot.input_sha256,
        "product_sha256": snapshot.product_sha256,
        "generated_at": snapshot.generated_at,
        "available_at": snapshot.available_at,
        "lanes": lanes,
        "counts": snapshot.counts.model_dump(mode="json"),
        "gaps": snapshot.gaps,
    }
