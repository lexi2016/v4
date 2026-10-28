"""Build a traceable exact-match current-ASR stock dictionary for one date."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds

from infrastructure.data_store import _date, _sha256
from infrastructure.owned_path import resolve_owned_path
from ops.capture_bilibili_fupan import _write


def _panel_path(pointer: Path) -> Path:
    panel = Path(pointer.read_bytes().decode("utf-8-sig").strip())
    if not panel.is_file():
        raise ValueError("selector panel pointer target is missing")
    return panel


def build_stockdict(
    data_root: Path,
    trade_date: str,
    *,
    capture_manifest_path: Path,
    panel_pointer: Path,
) -> dict[str, Any]:
    trade_date = _date(trade_date)
    capture_bytes = capture_manifest_path.read_bytes()
    capture = json.loads(capture_bytes.decode("utf-8-sig"))
    if capture.get("trade_date") != trade_date:
        raise ValueError("capture manifest date mismatch")
    if capture.get("status") != "ASR_REVIEW_REQUIRED":
        return {
            "schema_version": "v3_5.current_asr_pointer.v1",
            "status": "NOT_MATERIALIZED",
            "trade_date": trade_date,
            "reason": "ASR_TRANSCRIPT_NOT_READY",
            "source_capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
            "stock_mentions": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    panel = _panel_path(panel_pointer)
    table = ds.dataset(str(panel), format="parquet").to_table(
        columns=["trade_date", "ts_code", "name"],
        filter=ds.field("trade_date") == trade_date,
    )
    names: dict[str, str] = {}
    for row in table.to_pylist():
        code, name = str(row.get("ts_code") or ""), str(row.get("name") or "").strip()
        if code and name and code.endswith((".SZ", ".SH", ".BJ")):
            names[code] = name
    base = f"close_review_sources/{trade_date}/bilibili"
    transcript_root = resolve_owned_path(data_root, f"{base}/transcript")
    mentions: list[dict[str, Any]] = []
    transcript_evidence: list[dict[str, Any]] = []
    for video in capture.get("videos") or []:
        bv_id = str(video.get("bv_id") or "")
        for filename in video.get("transcript_files") or []:
            transcript = resolve_owned_path(data_root, f"{base}/transcript/{filename}")
            if not transcript.is_file() or transcript.parent != transcript_root:
                raise ValueError("capture transcript file is missing or escaped")
            raw = transcript.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            transcript_evidence.append({
                "bv_id": bv_id,
                "filename": filename,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
            })
            for code, name in names.items():
                count = text.count(name)
                if count:
                    mentions.append({
                        "bv_id": bv_id,
                        "stock_code": code,
                        "stock_name": name,
                        "mention_count": count,
                        "match_type": "EXACT_LOCAL_STOCK_NAME",
                        "source_file": filename,
                        "recommendation_status": "WATCH_ONLY",
                    })
    dictionary_sha = _sha256([{"stock_code": code, "stock_name": names[code]} for code in sorted(names)])
    mentions_relative = f"{base}/transcript_stockdict/stock_mentions.json"
    pointer_relative = f"{base}/transcript_stockdict/current_asr_pointer.json"
    mentions_payload = {
        "schema_version": "v3_5.asr_stock_mentions.v1",
        "trade_date": trade_date,
        "rows": mentions,
        "dictionary_sha256": dictionary_sha,
    }
    pointer = {
        "schema_version": "v3_5.current_asr_pointer.v1",
        "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY",
        "trade_date": trade_date,
        "source_capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
        "dictionary_sha256": dictionary_sha,
        "dictionary_row_count": len(names),
        "transcript_evidence": transcript_evidence,
        "stock_mentions": mentions,
        "stock_mentions_path": mentions_relative,
        "boundary": "仅本地证券名称精确命中；谐音、英文缩写和上下文歧义仍需抽查。",
        "cannot_confirm": ["ASR_STOCK_NAME_REVIEW_REQUIRED"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write(resolve_owned_path(data_root, mentions_relative), mentions_payload)
    _write(resolve_owned_path(data_root, pointer_relative), pointer)
    return pointer


def main() -> None:
    parser = argparse.ArgumentParser(description="Build exact-match Bilibili current-ASR stockdict")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--capture-manifest", required=True, type=Path)
    parser.add_argument("--panel-pointer", required=True, type=Path)
    args = parser.parse_args()
    pointer = build_stockdict(
        args.data_root,
        args.date,
        capture_manifest_path=args.capture_manifest,
        panel_pointer=args.panel_pointer,
    )
    print(json.dumps(pointer, ensure_ascii=False))


if __name__ == "__main__":
    main()
