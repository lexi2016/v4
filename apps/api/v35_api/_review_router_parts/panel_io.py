"""apps.api.v35_api.review_router: panel_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __panel_cannot_confirm_body(_v4_scope, /, requested_date, reasons):
    unique = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in reasons if _v4_global(_v4_scope, 'str')(item).strip()))
    return {
        "schema_version": _v4_global(_v4_scope, '_HK_PREFIX_PANEL_SCHEMA'),
        "status": "CANNOT_CONFIRM",
        "requested_date": requested_date,
        "asset_id": "",
        "run_id": "",
        "asset_status": "CANNOT_CONFIRM",
        "scope": {
            "historical_prefix_only": True,
            "max_event_year": 2025,
            "consumed_2026": False,
        },
        "source": None,
        "calendar": None,
        "binding": None,
        "export": None,
        "acceptance": {},
        "review": {
            "manual_review_status": "NOT_REVIEWED",
            "conclusion_status": "PENDING_EVIDENCE",
            "comparison_status": "CANNOT_CONFIRM",
            "conclusion": "历史前缀研究资产未通过固定绑定读取；不形成 alpha 或交易结论。",
            "no_alpha_claim": True,
        },
        "evidence": [],
        "cannot_confirm": unique or ["HK_PREFIX_RESEARCH_UNAVAILABLE"],
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def __unavailable_metric_body(_v4_scope, /):
    return {
        "evidence_status": "CANNOT_CONFIRM",
        "selected_count": None,
        "selected_codes": [],
        "hit_count": None,
        "hit_codes": [],
        "coverage": None,
        "precision": None,
        "coverage_pct": None,
        "precision_pct": None,
    }
