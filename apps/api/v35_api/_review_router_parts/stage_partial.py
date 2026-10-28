"""apps.api.v35_api.review_router: stage_partial (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __partial_stage_review_body(_v4_scope, /, trade_date, stage_rows, source_refs):
    source_sha = _v4_global(_v4_scope, '_sha256')(
        {"trade_date": trade_date, "source_refs": source_refs, "stage_rows": stage_rows}
    )
    cannot_confirm = [
        "REVIEW_CORE_BUNDLE_NOT_MATERIALIZED",
        "FORMAL_PRIOR_PLAN_NOT_MATERIALIZED",
        "FORMAL_BOARD_COVERAGE_NOT_MATERIALIZED",
        "FORMAL_MAINLINE_NOT_MATERIALIZED",
        "FORMAL_CORE_NOT_MATERIALIZED",
        "DAILY_VIDEO_NOT_LOCKED",
    ]
    review = _v4_global(_v4_scope, 'build_a_share_review')(
        trade_date,
        big_picture=[],
        mainlines=[],
        core_stocks=[],
        observation_pool=_v4_global(_v4_scope, 'deepcopy')(stage_rows),
        trigger_rows=[],
        quality_gate_rows=_v4_global(_v4_scope, 'deepcopy')(source_refs),
        source_sha256=source_sha,
        market_regime="CANNOT_CONFIRM",
        risk_tone="CANNOT_CONFIRM",
        cannot_confirm=cannot_confirm,
        model_review={
            "status": "NOT_MATERIALIZED",
            "cannot_confirm": ["A_SHARE_CLOSE_MODEL_NOT_MATERIALIZED"],
        },
        source_evidence=_v4_global(_v4_scope, 'deepcopy')(source_refs),
        source_role="V3_5_STAGE_EVIDENCE_PARTIAL",
    )
    review.update(
        {
            "status": "PARTIAL_STAGE_EVIDENCE",
            "headline": f"A股复盘 {trade_date} · 阶段候选仅作 WATCH_ONLY 验证锚",
            "stage_validation_rows": _v4_global(_v4_scope, 'deepcopy')(stage_rows),
            "summary_cards": [],
            "market_rows": [],
            "prior_plan_rows": [],
            "board_rows": [],
            "anchor_rows": [],
            "anchor_role_v3_rows": [],
            "intraday_handoff_rows": [],
            "catalyst_rows": [],
            "trigger_rows": [],
            "scenario_tree_rows": [],
            "video": {
                "status": "CANNOT_CONFIRM",
                "date_scope": "DAILY_VIDEO_NOT_LOCKED",
                "target_trade_date": trade_date,
                "trade_date": trade_date,
                "artifact_refs": [],
                "cannot_confirm": ["DAILY_VIDEO_NOT_LOCKED"],
            },
            "video_gap_rows": [],
            "source_status_rows": _v4_global(_v4_scope, 'deepcopy')(source_refs),
            "formal_pool_validation": {
                "status": "CANNOT_CONFIRM",
                "cannot_confirm": ["FORMAL_REVIEW_CORE_NOT_MATERIALIZED"],
            },
            "rule_adoption_rows": [],
            "video_learning_rows": [],
            "cannot_confirm_items": cannot_confirm,
            "source_run_id": "",
            "artifact_sha256": "",
            "review_core_bundle": {
                "status": "NOT_MATERIALIZED",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": trade_date,
                "cannot_confirm": ["REVIEW_CORE_BUNDLE_NOT_MATERIALIZED"],
            },
            "review_surface": {
                "tier": "V3_RICH_PARTIAL",
                "status": "PARTIAL_STAGE_EVIDENCE",
                "trade_date": trade_date,
                "source_role": "V3_5_NATIVE_STAGE_SNAPSHOT",
                "source_refs": _v4_global(_v4_scope, 'deepcopy')(source_refs),
                "stage_validation_count": _v4_global(_v4_scope, 'len')(stage_rows),
                "formal_sections": {
                    "prior_plan": "CANNOT_CONFIRM",
                    "board_coverage": "CANNOT_CONFIRM",
                    "mainlines": "CANNOT_CONFIRM",
                    "core_stocks": "CANNOT_CONFIRM",
                },
                "cannot_confirm": cannot_confirm,
            },
            **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
        }
    )
    return review
