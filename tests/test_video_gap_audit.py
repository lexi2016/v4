from __future__ import annotations

import json
from pathlib import Path

from domains.video_gap_audit import build_gap_audit, gap_row
from ops.build_video_gap_audit import materialize_gap_audit


def _review() -> dict:
    return {
        "trade_date": "20260731",
        "model_review": {
            "market_summary": {"up_count": 100},
            "previous_plan_realization": "CANNOT_CONFIRM_PREVIOUS_PLAN_REALIZATION_WITHOUT_BOUND_PRIOR_PLAN",
            "board_rows": [{"board_name": "金融"}],
            "anchor_role_rows": [{"stock_name": "浦发银行"}],
        },
        "trigger_rows": [{"direction": "风险"}],
    }


def test_gap_row_preserves_v3_field_contract() -> None:
    row = gap_row(
        "G001", "BV1exact", "复盘", "昨日预案兑现", "视频框架", "本地答案",
        "PLAN_TABLE_MISSING", "transcript.txt", "影响", "BLOCKED", "prior_plan_rows",
        "missing",
    )

    assert row == {
        "row_id": "G001", "bv_id": "BV1exact", "timestamp": "ASR_RAW_NO_TIMESTAMP",
        "title_or_segment": "复盘", "item": "昨日预案兑现",
        "video_question_or_framework": "视频框架", "video_framework": "视频框架",
        "current_review_skill_rule": "昨日预案兑现",
        "current_local_review_behavior": "本地答案", "local_review_answer": "本地答案",
        "gap_type": "PLAN_TABLE_MISSING", "evidence_route": "transcript.txt",
        "evidence_path": "transcript.txt", "impact": "影响", "decision": "BLOCKED",
        "status": "BLOCKED", "backwritten_to": "prior_plan_rows", "cannot_confirm": "missing",
    }


def test_fixed_v3_gap_matrix_uses_local_outputs_without_changing_model() -> None:
    review = _review()
    result = build_gap_audit(
        "20260731",
        bv_id="BV1exact",
        title="收盘复盘",
        transcript_text="昨天计划兑现，指数放量，早盘接棒，主线风险，龙头容量，研报催化，明天失效。",
        transcript_path="transcript/BV1exact.txt",
        review=review,
        stock_mentions=[{
            "bv_id": "BV1exact", "stock_code": "600000.SH", "stock_name": "浦发银行",
        }],
    )

    assert result["status"] == "VIDEO_GAP_AUDIT_READY"
    assert result["gap_row_count"] == 8
    by_item = {row["item"]: row for row in result["gap_rows"]}
    assert by_item["昨日预案兑现"]["decision"] == "LOCAL_REVIEW_WEAK_OR_MISSING"
    assert by_item["指数量能与风险状态"]["decision"] == "LOCAL_REVIEW_HAS_OUTPUT"
    assert by_item["主线/风险主线分层"]["decision"] == "LOCAL_REVIEW_HAS_OUTPUT"
    assert by_item["龙头/容量锚/风险锚"]["decision"] == "LOCAL_REVIEW_HAS_OUTPUT"
    assert by_item["研报/资讯催化"]["decision"] == "LOCAL_REVIEW_WEAK_OR_MISSING"
    assert by_item["明日触发/失效"]["decision"] == "LOCAL_REVIEW_HAS_OUTPUT"
    assert by_item["视频口播股票名"]["decision"] == "ASR_REVIEW_REQUIRED"
    assert review == _review()
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_missing_asr_dependency_returns_before_reading_review(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    alignment = tmp_path / "alignment.json"
    current.write_text(json.dumps({"trade_date": "20260731", "status": "NOT_MATERIALIZED"}), encoding="utf-8")
    alignment.write_text(json.dumps({"trade_date": "20260731", "status": "NOT_MATERIALIZED"}), encoding="utf-8")

    result = materialize_gap_audit(
        tmp_path / "data",
        "20260731",
        current_asr_pointer_path=current,
        alignment_pointer_path=alignment,
        review_path=tmp_path / "missing-review.json",
    )

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["reason"] == "ASR_STOCKDICT_NOT_READY"
    assert not (tmp_path / "data").exists()
