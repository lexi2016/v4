"""Focused regressions for hourly research entity attribution (R1-ENTITY)."""
from __future__ import annotations

from domains.research_hourly import build_research_lane_snapshot


TRADE_DATE = "20260907"
STOCK_MASTER = {
    "000428": {"name": "华天酒店"},
    "000823": {"name": "超声电子"},
    "001215": {"name": "千味央厨"},
    "300123": {"name": "迅捷兴"},
    "300456": {"name": "北特科技"},
    "600789": {"name": "青岛啤酒"},
}


def _item(*, title: str, raw_text: str, candidates: list[str], raw_id: str) -> dict:
    return {
        "raw_id": raw_id,
        "source_type": "zsxq",
        "source_name": "知识星球",
        "source_path": "research_module/runtime_outputs/zsxq_hourly/20260907/1900.json",
        "url": f"https://wx.zsxq.com/topic/{raw_id}",
        "title": title,
        "raw_text": raw_text,
        "published_at": "2026-09-07T18:32:58+08:00",
        "source_evidence_level": "L3_STRONG",
        "source_confidence": "HIGH",
        "mentioned_stock_candidates": candidates,
    }


def test_candidate_tags_alone_cannot_bind_stock_evidence() -> None:
    """The frozen 1900 mismatches must stay unassigned/CANNOT_CONFIRM."""
    rows = [
        _item(
            title="20260907今日段子汇总",
            raw_text="迅捷兴：公司拥有多个制造基地，PCB业务持续推进。",
            candidates=["华天酒店", "000428"],
            raw_id="mismatch-huatian",
        ),
        _item(
            title="北特科技：机器人丝杠研发",
            raw_text="北特科技根据客户需求推进人形机器人用丝杠产品研发。",
            candidates=["超声电子", "000823"],
            raw_id="mismatch-chaosheng",
        ),
        _item(
            title="大众品8月跟踪反馈",
            raw_text="青岛啤酒销量下滑，会稽山保持增长。",
            candidates=["千味央厨", "001215"],
            raw_id="mismatch-qianwei",
        ),
    ]

    snapshot = build_research_lane_snapshot(TRADE_DATE, rows, STOCK_MASTER)

    evidence = snapshot["stock_research_timeline"]
    assert {row["stock_code"] for row in evidence} == {"300123", "300456", "600789"}
    assert all(row["is_direct_stock_mention"] for row in evidence)
    assert all(row["evidence_level"] == "L3_STRONG" for row in evidence)
    assert not {"000428", "000823", "001215"}.intersection(
        row["stock_code"] for row in evidence
    )
    assert snapshot["research_quality_summary"]["stock_evidence_count"] == 3
    assert snapshot["research_quality_summary"]["cannot_confirm_count"] == 3
    assert all(
        row["reason"] == "STOCK_CANDIDATE_ENTITY_NOT_VERIFIED"
        for row in snapshot["cannot_confirm"]
        if isinstance(row, dict) and "stock_code" in row
    )
    assert snapshot["default_status"] == "RESEARCH_ONLY"
    assert snapshot["write_policy"] == "read_only"


def test_direct_same_entity_sentence_still_produces_evidence() -> None:
    snapshot = build_research_lane_snapshot(
        TRADE_DATE,
        [
            _item(
                title="华天酒店经营更新",
                raw_text="华天酒店披露新业务进展，酒店经营保持稳定。",
                candidates=["华天酒店", "000428"],
                raw_id="direct-huatian",
            )
        ],
        STOCK_MASTER,
    )

    evidence = snapshot["stock_research_timeline"]
    assert len(evidence) == 1
    assert evidence[0]["stock_code"] == "000428"
    assert evidence[0]["is_direct_stock_mention"] is True
    assert evidence[0]["evidence_level"] == "L3_STRONG"
    assert evidence[0]["evidence_sentence"] == "华天酒店披露新业务进展，酒店经营保持稳定。"


def test_direct_code_in_source_keeps_code_specific_sentence() -> None:
    snapshot = build_research_lane_snapshot(
        TRADE_DATE,
        [
            _item(
                title="公告 000428",
                raw_text="000428新业务订单落地，经营保持稳定。",
                candidates=[],
                raw_id="direct-code-huatian",
            )
        ],
        STOCK_MASTER,
    )

    evidence = snapshot["stock_research_timeline"]
    assert len(evidence) == 1
    assert evidence[0]["stock_code"] == "000428"
    assert evidence[0]["evidence_sentence"] == "000428新业务订单落地，经营保持稳定。"


def test_verified_source_entity_receipt_can_bind_without_text_match() -> None:
    snapshot = build_research_lane_snapshot(
        TRADE_DATE,
        [
            {
                **_item(
                    title="跨公司产业链跟踪",
                    raw_text="合作方披露产业链订单变化。",
                    candidates=["华天酒店", "000428"],
                    raw_id="mapped-huatian",
                ),
                "source_entity_receipt": {
                    "status": "VERIFIED",
                    "stock_code": "000428",
                    "stock_name": "华天酒店",
                    "receipt_path": "receipts/entity/mapped-huatian.json",
                    "receipt_sha256": "a" * 64,
                    "evidence_sentence": "receipt confirms the source belongs to 华天酒店。",
                },
            }
        ],
        STOCK_MASTER,
    )

    evidence = snapshot["stock_research_timeline"]
    assert len(evidence) == 1
    assert evidence[0]["stock_code"] == "000428"
    assert evidence[0]["is_direct_stock_mention"] is False
    assert evidence[0]["is_theme_only_mapping"] is False
    assert evidence[0]["evidence_level"] == "L3_STRONG"
    assert evidence[0]["cannot_confirm"] == []
    assert evidence[0]["quality_flags"] == [
        "SOURCE_ENTITY_RECEIPT:receipts/entity/mapped-huatian.json",
    ]


def test_incomplete_entity_receipt_cannot_bind_candidate_tag() -> None:
    snapshot = build_research_lane_snapshot(
        TRADE_DATE,
        [
            {
                **_item(
                    title="跨公司产业链跟踪",
                    raw_text="合作方披露产业链订单变化。",
                    candidates=["华天酒店", "000428"],
                    raw_id="unverified-huatian",
                ),
                "source_entity_receipt": {
                    "stock_code": "000428",
                    "receipt_path": "receipts/entity/unverified-huatian.json",
                },
            }
        ],
        STOCK_MASTER,
    )

    assert snapshot["stock_research_timeline"] == []
    assert snapshot["cannot_confirm"][0]["stock_code"] == "000428"
