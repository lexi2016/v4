"""domains.research_hourly: lane_snapshot (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_research_lane_snapshot_body(_v4_scope, /, trade_date, source_rows, stock_master, pool_rows):
    raw_items = _v4_global(_v4_scope, 'build_raw_items')(trade_date, source_rows)
    items = _v4_global(_v4_scope, 'normalize_research_items')(raw_items)
    evidence = _v4_global(_v4_scope, 'extract_stock_evidence')(items, stock_master)
    daily = _v4_global(_v4_scope, 'aggregate_stock_research_daily')(evidence)
    bridges = _v4_global(_v4_scope, 'build_research_pool_bridge')(trade_date, daily, evidence, pool_rows)
    unassigned = _v4_global(_v4_scope, 'unassigned_entity_notes')(items, stock_master)
    cannot_confirm = []
    for item in items:
        for reason in item.cannot_confirm:
            cannot_confirm.append({"item_id": item.item_id, "reason": reason})
    cannot_confirm.extend(unassigned)
    summary = {
        "raw_item_count": _v4_global(_v4_scope, 'len')(raw_items),
        "research_item_count": _v4_global(_v4_scope, 'len')(items),
        "stock_evidence_count": _v4_global(_v4_scope, 'len')(evidence),
        "stock_daily_count": _v4_global(_v4_scope, 'len')(daily),
        "bridge_count": _v4_global(_v4_scope, 'len')(bridges),
        "l3_strong_count": _v4_global(_v4_scope, 'sum')(row.evidence_level == "L3_STRONG" for row in evidence),
        "l2_medium_count": _v4_global(_v4_scope, 'sum')(row.evidence_level == "L2_MEDIUM" for row in evidence),
        "l1_weak_count": _v4_global(_v4_scope, 'sum')(row.evidence_level == "L1_WEAK" for row in evidence),
        "formal_overlap_count": _v4_global(_v4_scope, 'sum')(row.formal_overlap for row in bridges),
        "cannot_confirm_count": _v4_global(_v4_scope, 'len')(cannot_confirm),
    }
    payload = {
        "ok": True,
        "schema_version": "v3_research_lane.v2",
        "trade_date": trade_date,
        "module_id": "research_intelligence",
        "write_policy": _v4_global(_v4_scope, 'READ_ONLY_POLICY'),
        "default_status": _v4_global(_v4_scope, 'RESEARCH_ONLY'),
        "buy_gate_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
        "live_order_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
        "research_quality_summary": summary,
        "raw_items": [_v4_global(_v4_scope, 'as_plain_dict')(row) for row in raw_items],
        "research_items": [_v4_global(_v4_scope, 'as_plain_dict')(row) for row in items],
        "stock_research_timeline": [_v4_global(_v4_scope, 'as_plain_dict')(row) for row in evidence],
        "stock_research_daily": [_v4_global(_v4_scope, 'as_plain_dict')(row) for row in daily],
        "research_pool_bridge": [_v4_global(_v4_scope, 'as_plain_dict')(row) for row in bridges],
        "source_manifest": {
            "source_types": _v4_global(_v4_scope, 'sorted')({row.source_type for row in raw_items}),
            "generated_at": _v4_global(_v4_scope, 'datetime').now().strftime("%Y-%m-%d %H:%M:%S"),
            "module_path": "v3.5/domains/research_hourly",
            "version": _v4_global(_v4_scope, 'datetime').now().strftime("%Y%m%d%H%M%S") + "-" + _v4_global(_v4_scope, 'stable_hash')(
                "|".join([trade_date, *[row.raw_id for row in raw_items], *[row.evidence_id for row in evidence]])
            )[:8],
            "event_id": "",
        },
        "quality_status": "QUALITY_PASS" if daily else "QUALITY_FAIL",
        "stock_timeline_available": _v4_global(_v4_scope, 'bool')(daily and evidence),
        "source_health": {
            "research_module_snapshot": "READY" if daily or raw_items else "EMPTY_OR_UNMAPPED",
            "stock_timeline": "READY" if evidence else "EMPTY_OR_UNMAPPED",
        },
        "integration_state": "generated_snapshot_live",
        "morning_news": {
            "status": "GENERATED_SNAPSHOT",
            "articles": [],
            "articles_count": 0,
            "write_policy": _v4_global(_v4_scope, 'READ_ONLY_POLICY'),
            "buy_gate_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
            "live_order_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
            "cannot_confirm_items": [],
        },
        "news_workbench": {
            "schema_version": "generated_snapshot.v1",
            "status": "GENERATED_SNAPSHOT",
            "quality_summary": summary,
            "action_rows": [],
            "source_health": {},
            "cannot_confirm_items": [],
            "write_policy": _v4_global(_v4_scope, 'READ_ONLY_POLICY'),
            "buy_gate_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
            "live_order_effect": _v4_global(_v4_scope, 'NO_BUY_GATE'),
        },
        "research_sections": [
            {"section_id": "stock_research_daily", "display_name": "股票主线", "count": _v4_global(_v4_scope, 'len')(daily), "status": "READY" if daily else "EMPTY_OR_UNMAPPED", "source_path": "stock_research_daily"},
            {"section_id": "stock_research_timeline", "display_name": "股票时间线", "count": _v4_global(_v4_scope, 'len')(evidence), "status": "READY" if evidence else "EMPTY_OR_UNMAPPED", "source_path": "stock_research_timeline"},
        ],
        "research_cards": [],
        "lanes": [
            {
                "lane_id": "v3_research_module_generated_snapshot",
                "display_name": "v3.5 研报模块生成快照",
                "status": _v4_global(_v4_scope, 'RESEARCH_ONLY'),
                "source_path": "research/hourly/latest.json",
                "opens_buy_gate": False,
                "next_action": "生成完成后供 8872 只读页面读取。",
            }
        ],
        "cannot_confirm": cannot_confirm + [
            {"module": "research_intelligence", "reason": "RESEARCH_ONLY_NO_BUY_GATE"}
        ],
    }
    _v4_global(_v4_scope, 'assert_research_only')(payload)
    return payload
