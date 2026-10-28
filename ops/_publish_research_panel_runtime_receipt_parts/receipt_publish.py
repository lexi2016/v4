"""ops.publish_research_panel_runtime_receipt: receipt_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _publish_research_panel_status_body(_v4_scope, /, *, business_date, data_root, producer_receipt_root, a_producer_receipt_root, selector_pointer, backtest_pointer, formula_generation_pointer, close_review_path, close_review_receipt_path, supersedes_sha256):
    date = _v4_global(_v4_scope, '_date')(business_date)
    root = _v4_global(_v4_scope, '_allowed_data_root')(data_root)
    output_dir = root / "runtime_graph" / "evidence" / "research_panel_status" / date
    a_status = _v4_global(_v4_scope, '_publish_a')(
        date,
        a_producer_receipt_root if a_producer_receipt_root is not None else producer_receipt_root,
        selector_pointer,
        backtest_pointer,
        formula_generation_pointer,
        owner_bound=a_producer_receipt_root is not None,
    )
    hk_status = _v4_global(_v4_scope, '_publish_hk')(date, producer_receipt_root, close_review_path, close_review_receipt_path)
    destinations = {
        "A": output_dir / "ashare_research_panel.json",
        "HK": output_dir / "hkconnect_research_panel.json",
    }
    a_supersedes = _v4_global(_v4_scope, '_supersedes_for_lane')(supersedes_sha256, "A")
    hk_supersedes = _v4_global(_v4_scope, '_supersedes_for_lane')(supersedes_sha256, "HK")
    a_status = _v4_global(_v4_scope, '_commit_lane')(destinations["A"], a_status, supersedes_sha256=a_supersedes)
    hk_status = _v4_global(_v4_scope, '_commit_lane')(destinations["HK"], hk_status, supersedes_sha256=hk_supersedes)
    return {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA'),
        "business_date": date,
        "lanes": {"A": a_status, "HK": hk_status},
        "paths": {lane: _v4_global(_v4_scope, 'str')(path) for lane, path in destinations.items()},
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
