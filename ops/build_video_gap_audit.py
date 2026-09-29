"""Materialize the V3-equivalent video gap audit for one close review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from domains.video_gap_audit import build_gap_audit
from infrastructure.data_store import _date
from infrastructure.owned_path import resolve_owned_path
from ops.capture_bilibili_fupan import _write


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes().decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    return payload


def materialize_gap_audit(
    data_root: Path,
    trade_date: str,
    *,
    current_asr_pointer_path: Path,
    alignment_pointer_path: Path,
    review_path: Path,
    title: str = "",
) -> dict[str, Any]:
    trade_date = _date(trade_date)
    current_asr = _object(current_asr_pointer_path)
    alignment = _object(alignment_pointer_path)
    if current_asr.get("trade_date") != trade_date or alignment.get("trade_date") != trade_date:
        raise ValueError("video gap dependency date mismatch")
    if current_asr.get("status") != "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY":
        return _not_materialized(trade_date, "ASR_STOCKDICT_NOT_READY")
    if alignment.get("status") != "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY":
        return _not_materialized(trade_date, "VIDEO_OCR_ALIGNMENT_NOT_READY")

    review = _object(review_path)
    if review.get("trade_date") != trade_date:
        raise ValueError("review date mismatch")
    transcript_parts: list[str] = []
    transcript_paths: list[str] = []
    base = f"close_review_sources/{trade_date}/bilibili/transcript"
    for evidence in current_asr.get("transcript_evidence") or []:
        filename = str(evidence.get("filename") or "")
        transcript = resolve_owned_path(data_root, f"{base}/{filename}")
        if not filename or not transcript.is_file():
            raise ValueError("current ASR transcript evidence is missing")
        transcript_parts.append(transcript.read_bytes().decode("utf-8-sig", errors="replace"))
        transcript_paths.append(f"{base}/{filename}")
    bv_id = str((current_asr.get("transcript_evidence") or [{}])[0].get("bv_id") or "")
    result = build_gap_audit(
        trade_date,
        bv_id=bv_id,
        title=title,
        transcript_text="\n".join(transcript_parts),
        transcript_path=";".join(transcript_paths),
        review=review,
        stock_mentions=current_asr.get("stock_mentions") or [],
    )
    output = f"close_review_sources/{trade_date}/bilibili/video_gap/video_gap_audit.json"
    result["artifact_path"] = output
    _write(resolve_owned_path(data_root, output), result)
    return result


def _not_materialized(trade_date: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "v3_5.video_gap_audit.v1",
        "status": "NOT_MATERIALIZED",
        "trade_date": trade_date,
        "reason": reason,
        "gap_rows": [],
        "gap_row_count": 0,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V3-equivalent close-review/video gap audit")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--current-asr-pointer", required=True, type=Path)
    parser.add_argument("--alignment-pointer", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--title", default="")
    args = parser.parse_args()
    result = materialize_gap_audit(
        args.data_root,
        args.date,
        current_asr_pointer_path=args.current_asr_pointer,
        alignment_pointer_path=args.alignment_pointer,
        review_path=args.review,
        title=args.title,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
