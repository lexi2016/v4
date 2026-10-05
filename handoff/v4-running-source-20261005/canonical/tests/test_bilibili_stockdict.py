from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ops.build_bilibili_stockdict import build_stockdict


def _panel(tmp_path: Path) -> Path:
    panel = tmp_path / "selector.parquet"
    pd.DataFrame([
        {"trade_date": "20260731", "ts_code": "600000.SH", "name": "浦发银行"},
        {"trade_date": "20260731", "ts_code": "000001.SZ", "name": "平安银行"},
    ]).to_parquet(panel, index=False)
    pointer = tmp_path / "panel.txt"
    pointer.write_text(str(panel), encoding="utf-8-sig")
    return pointer


def test_exact_local_name_match_builds_current_asr_pointer_without_fuzzy_rewrite(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    transcript = data_root / "close_review_sources" / "20260731" / "bilibili" / "transcript" / "BV1same.funasr_raw.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("浦发银行出现两次，浦发银行。中继巨创仍然歧义。", encoding="utf-8")
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({
        "trade_date": "20260731", "status": "ASR_REVIEW_REQUIRED",
        "videos": [{"bv_id": "BV1same", "transcript_files": [transcript.name]}],
    }), encoding="utf-8")

    pointer = build_stockdict(
        data_root, "20260731", capture_manifest_path=capture, panel_pointer=_panel(tmp_path)
    )

    assert pointer["status"] == "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"
    assert pointer["stock_mentions"] == [{
        "bv_id": "BV1same", "stock_code": "600000.SH", "stock_name": "浦发银行",
        "mention_count": 2, "match_type": "EXACT_LOCAL_STOCK_NAME",
        "source_file": transcript.name, "recommendation_status": "WATCH_ONLY",
    }]
    assert pointer["cannot_confirm"] == ["ASR_STOCK_NAME_REVIEW_REQUIRED"]
    assert pointer["production_allowed"] is False


def test_missing_asr_returns_typed_not_materialized_without_reading_panel(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({"trade_date": "20260731", "status": "NOT_MATERIALIZED"}), encoding="utf-8")

    pointer = build_stockdict(
        tmp_path / "data", "20260731", capture_manifest_path=capture,
        panel_pointer=tmp_path / "missing-panel.txt",
    )

    assert pointer["status"] == "NOT_MATERIALIZED"
    assert pointer["reason"] == "ASR_TRANSCRIPT_NOT_READY"
