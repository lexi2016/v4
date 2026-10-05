"""Materialize the V3-equivalent video frame/ASR/news alignment for one date."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from domains.video_ocr_alignment import build_alignment
from infrastructure.data_store import _date
from infrastructure.owned_path import resolve_owned_path
from ops.capture_bilibili_fupan import _write


def _payload(path: Path | None) -> Any:
    if path is None:
        return []
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _rows(path: Path | None) -> list[dict[str, Any]]:
    payload = _payload(path)
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("evidence input must contain an object row list")
    return rows


def materialize_alignment(
    data_root: Path,
    trade_date: str,
    *,
    current_asr_pointer_path: Path,
    spotcheck_path: Path | None = None,
    asr_segments_path: Path | None = None,
    news_path: Path | None = None,
    anchors_path: Path | None = None,
    boards_path: Path | None = None,
    tdx_path: Path | None = None,
) -> dict[str, Any]:
    trade_date = _date(trade_date)
    pointer = _payload(current_asr_pointer_path)
    if not isinstance(pointer, dict):
        raise ValueError("current ASR pointer must be an object")
    if pointer.get("trade_date") != trade_date:
        raise ValueError("current ASR pointer date mismatch")
    if pointer.get("status") != "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY":
        return build_alignment(trade_date, current_asr_pointer=pointer, spotcheck_rows=[])

    result = build_alignment(
        trade_date,
        current_asr_pointer=pointer,
        spotcheck_rows=_rows(spotcheck_path),
        asr_segments=_rows(asr_segments_path),
        news_rows=_rows(news_path),
        anchor_rows=_rows(anchors_path),
        board_rows=_rows(boards_path),
        tdx_rows=_rows(tdx_path),
    )
    base = f"close_review_sources/{trade_date}/bilibili/video_ocr_alignment"
    if result["status"] == "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY":
        artifact_relative = f"{base}/alignment.json"
        result["artifact_path"] = artifact_relative
        _write(resolve_owned_path(data_root, artifact_relative), result)
        _write(resolve_owned_path(data_root, f"{base}/alignment_pointer.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V3-equivalent video OCR/ASR/news alignment")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--current-asr-pointer", required=True, type=Path)
    parser.add_argument("--spotcheck", type=Path)
    parser.add_argument("--asr-segments", type=Path)
    parser.add_argument("--news", type=Path)
    parser.add_argument("--anchors", type=Path)
    parser.add_argument("--boards", type=Path)
    parser.add_argument("--tdx", type=Path)
    args = parser.parse_args()
    result = materialize_alignment(
        args.data_root,
        args.date,
        current_asr_pointer_path=args.current_asr_pointer,
        spotcheck_path=args.spotcheck,
        asr_segments_path=args.asr_segments,
        news_path=args.news,
        anchors_path=args.anchors,
        boards_path=args.boards,
        tdx_path=args.tdx,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
