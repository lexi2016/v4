"""Offline importer for explicit, read-only A-share review reference exports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from domains.a_share_review import build_a_share_review
from infrastructure.a_share_review_store import AShareReviewStore


def _list(source: Mapping[str, Any], *names: str) -> list[dict[str, Any]]:
    for name in names:
        if name not in source:
            continue
        value = source[name]
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        if any(not isinstance(row, Mapping) for row in value):
            raise ValueError(f"{name} rows must be objects")
        return [dict(row) for row in value]
    return []


def normalize_a_share_review_reference(source: Any, source_sha256: str) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValueError("invalid A-share review export")
    nested_markets = source.get("market_reviews")
    review = nested_markets.get("A") if isinstance(nested_markets, Mapping) else source
    if not isinstance(review, Mapping):
        raise ValueError("invalid A-share review export")
    trade_date = str(review.get("trade_date") or review.get("review_date") or source.get("trade_date") or source.get("review_date") or "")
    return build_a_share_review(
        trade_date,
        big_picture=_list(review, "big_picture", "first_screen_big_picture", "首屏大局观"),
        mainlines=_list(review, "mainlines", "video_methodology_blocks", "视频方法字段"),
        core_stocks=_list(review, "core_stocks", "localized_role_rows", "中文角色表"),
        observation_pool=_list(review, "observation_pool"),
        trigger_rows=_list(review, "next_day_trigger_tree", "next_day_trigger_tree_v2", "明日触发树"),
        quality_gate_rows=_list(review, "quality_gate", "human_video_gap_scorecard", "页面对视频差距评分"),
        source_sha256=source_sha256,
    )


def import_reference_file(store: AShareReviewStore, source: Path) -> dict[str, str]:
    source_bytes = source.read_bytes()
    payload = json.loads(source_bytes.decode("utf-8-sig"))
    return store.import_review(
        normalize_a_share_review_reference(payload, hashlib.sha256(source_bytes).hexdigest())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an explicit A-share review export")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_reference_file(AShareReviewStore(args.data_root), args.input), ensure_ascii=False))


if __name__ == "__main__":
    main()
