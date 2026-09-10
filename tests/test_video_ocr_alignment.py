from __future__ import annotations

import json
from pathlib import Path

from domains.video_ocr_alignment import build_alignment
from ops.build_video_ocr_alignment import materialize_alignment


def _pointer(status: str = "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY") -> dict:
    return {
        "trade_date": "20260731",
        "status": status,
        "transcript_evidence": [{"bv_id": "BV1exact"}],
    }


def test_v3_frame_alignment_preserves_role_news_board_and_tdx_semantics() -> None:
    result = build_alignment(
        "20260731",
        current_asr_pointer=_pointer(),
        spotcheck_rows=[{
            "frame_time": "12.5",
            "frame_path": "frames/600000_浦发银行_001.png",
            "segment_index": "7",
            "asr_text": "容量中军浦发银行",
            "status": "FRAME_READY",
        }],
        asr_segments=[{"segment_index": "7", "start": 10, "end": 15, "text": "容量中军浦发银行"}],
        news_rows=[{"stock_code": "600000", "hit_status": "NEWS_HIT", "source_title": "公告", "source_url": "https://example.invalid"}],
        anchor_rows=[{"stock": "浦发银行", "theme": "金融", "role_type": "capacity_anchor"}],
        board_rows=[{"stock_code": "600000", "stock_name": "浦发银行"}],
        tdx_rows=[{"ts_code": "600000.SH", "pct_chg": "7.5", "amplitude_pct": "8.0", "amount_yi": "12"}],
    )

    assert result["status"] == "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY"
    assert result["row_count"] == 1
    row = result["rows"][0]
    assert row["stock_code"] == "600000"
    assert row["stock_name"] == "浦发银行"
    assert row["video_role"] == "capacity_anchor"
    assert row["news_hit_status"] == "NEWS_HIT"
    assert row["local_role_status"] == "LOCAL_ROLE_MATCH"
    assert row["board_status"] == "BOARD_MATCH"
    assert row["price_volume_status"] == "SHARP_UP"
    assert row["final_boundary"] == "SHADOW_RESEARCH_ONLY_NO_BUY_GATE"
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_ready_asr_without_spotcheck_stays_cannot_confirm() -> None:
    result = build_alignment(
        "20260731",
        current_asr_pointer=_pointer(),
        spotcheck_rows=[],
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["reason"] == "VIDEO_TABLE_CELLS_MISSING_INPUT"
    assert result["rows"] == []


def test_missing_asr_returns_before_reading_optional_inputs(tmp_path: Path) -> None:
    pointer = tmp_path / "current_asr.json"
    pointer.write_text(json.dumps(_pointer("NOT_MATERIALIZED")), encoding="utf-8")

    result = materialize_alignment(
        tmp_path / "data",
        "20260731",
        current_asr_pointer_path=pointer,
        spotcheck_path=tmp_path / "missing.json",
    )

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["reason"] == "ASR_STOCKDICT_NOT_READY"
    assert not (tmp_path / "data").exists()
