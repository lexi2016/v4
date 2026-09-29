"""Build the exact-date A-share review from the V3 selector close panel."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds

from domains.a_share_close_model import build_close_model
from domains.a_share_review import build_a_share_review
from domains.close_review_chain import build_close_review_chain
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.data_store import _sha256


_COLUMNS = [
    "trade_date", "ts_code", "name", "pct_chg", "amount", "bar_close_pos",
    "tdx_industry_code", "tdx_industry_name",
]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _panel_path(pointer: Path) -> Path:
    raw = pointer.read_bytes()
    path = Path(raw.decode("utf-8-sig").strip())
    if not path.is_file():
        raise ValueError("selector panel pointer target is missing")
    return path


def _scenario_rows(model: dict[str, Any], trade_date: str) -> list[dict[str, Any]]:
    result = []
    for direction, row in model["scenario_tree"].items():
        result.append({
            "trade_date": trade_date,
            "direction": direction,
            "probability": row["probability"],
            "upgrade": "；".join(row.get("open_trigger", [])),
            "invalidation": "；".join(row.get("invalidation", [])),
            "producer_type": "DETERMINISTIC_PYTHON",
        })
    return result


def build_review_from_panel(
    data_root: Path,
    trade_date: str,
    *,
    panel_pointer: Path,
    run_id: str | None = None,
    video_acceptance: dict[str, Any] | None = None,
    video_capture: dict[str, Any] | None = None,
    stockdict_pointer: dict[str, Any] | None = None,
    ocr_alignment_pointer: dict[str, Any] | None = None,
    video_gap_pointer: dict[str, Any] | None = None,
    replace_previous_sha: str | None = None,
) -> dict[str, Any]:
    pointer_before = panel_pointer.read_bytes()
    panel = _panel_path(panel_pointer)
    panel_stat = (panel.stat().st_size, panel.stat().st_mtime_ns)
    table = ds.dataset(str(panel), format="parquet").to_table(
        columns=_COLUMNS,
        filter=ds.field("trade_date") == trade_date,
    )
    model = build_close_model(
        table.to_pandas(),
        trade_date,
        run_id or f"REPLAY_RESEARCH_V1_{trade_date}_001",
    )
    panel_sha = _file_sha256(panel)
    if panel_pointer.read_bytes() != pointer_before or (
        panel.stat().st_size, panel.stat().st_mtime_ns
    ) != panel_stat:
        raise ValueError("selector close input changed during materialization")
    source_evidence = [{
        "source_id": "selector_ready_panel",
        "trade_date": trade_date,
        "row_count": table.num_rows,
        "raw_sha256": panel_sha,
        "date_role": "business_date_close",
    }]
    source_sha = _sha256({
        "trade_date": trade_date,
        "panel_sha256": panel_sha,
        "model_contract": "V3_BUILD_DAILY_REPLAY_RESEARCH_V1_DETERMINISTIC_CORE",
    })
    market = model["market_summary"]
    close_chain = build_close_review_chain(
        trade_date,
        close_source_evidence=source_evidence,
        video_acceptance=video_acceptance,
        video_capture=video_capture,
        stockdict_pointer=stockdict_pointer,
        ocr_alignment_pointer=ocr_alignment_pointer,
        video_gap_pointer=video_gap_pointer,
    )
    review = build_a_share_review(
        trade_date,
        big_picture=[{
            "trade_date": trade_date,
            "title": "市场总览",
            **market,
            "producer_type": "DETERMINISTIC_PYTHON",
        }],
        mainlines=model["board_rows"],
        core_stocks=[],
        observation_pool=model["anchor_role_rows"],
        trigger_rows=_scenario_rows(model, trade_date),
        quality_gate_rows=[
            {
                "trade_date": trade_date,
                "item": "同日视频",
                "status": model["target_video_review_status"],
                "producer_type": "SOURCE_GATE",
            },
            {
                "trade_date": trade_date,
                "item": "15:00 PIT",
                "status": "CANNOT_CONFIRM_STRICT_D0_1500_PANEL",
                "producer_type": "SOURCE_GATE",
            },
            {
                "trade_date": trade_date,
                "item": "LLM语义层",
                "status": model["semantic_model_status"],
                "producer_type": "SOURCE_GATE",
            },
        ],
        source_sha256=source_sha,
        market_regime=str(market["regime"]),
        risk_tone=str(market["regime"]),
        cannot_confirm=[
            "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED",
            "CANNOT_CONFIRM_STRICT_D0_1500_PANEL",
            "FORMAL_GENERALIZATION_PENDING",
        ],
        model_review=model,
        source_evidence=source_evidence,
        source_role="V3_5_NATIVE_CLOSE_MODEL",
        close_chain=close_chain,
    )
    store = AShareReviewStore(Path(data_root))
    if replace_previous_sha is not None:
        publication = store.replace_review(
            review,
            expected_sha256=replace_previous_sha,
            reason="replace invalid legacy review with native V3.5 close model",
        )
    else:
        publication = store.import_review(review)
    return {"review": review, "publication": publication}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the V3.5 deterministic A-share close review"
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--panel-pointer", required=True, type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--video-acceptance", type=Path)
    parser.add_argument("--video-capture", type=Path)
    parser.add_argument("--stockdict-pointer", type=Path)
    parser.add_argument("--ocr-alignment-pointer", type=Path)
    parser.add_argument("--video-gap-pointer", type=Path)
    parser.add_argument("--replace-previous-sha")
    args = parser.parse_args()
    video_acceptance = None
    if args.video_acceptance is not None:
        video_acceptance = json.loads(args.video_acceptance.read_text(encoding="utf-8-sig"))
    video_capture = None
    if args.video_capture is not None:
        video_capture = json.loads(args.video_capture.read_text(encoding="utf-8-sig"))
    stockdict_pointer = None
    if args.stockdict_pointer is not None:
        stockdict_pointer = json.loads(args.stockdict_pointer.read_text(encoding="utf-8-sig"))
    ocr_alignment_pointer = None
    if args.ocr_alignment_pointer is not None:
        ocr_alignment_pointer = json.loads(args.ocr_alignment_pointer.read_text(encoding="utf-8-sig"))
    video_gap_pointer = None
    if args.video_gap_pointer is not None:
        video_gap_pointer = json.loads(args.video_gap_pointer.read_text(encoding="utf-8-sig"))
    result = build_review_from_panel(
        args.data_root,
        args.date,
        panel_pointer=args.panel_pointer,
        run_id=args.run_id,
        video_acceptance=video_acceptance,
        video_capture=video_capture,
        stockdict_pointer=stockdict_pointer,
        ocr_alignment_pointer=ocr_alignment_pointer,
        video_gap_pointer=video_gap_pointer,
        replace_previous_sha=args.replace_previous_sha,
    )
    print(json.dumps({
        "status": result["review"]["model_review"]["status"],
        "trade_date": result["review"]["trade_date"],
        "market_rows": result["review"]["model_review"]["market_summary"]["up_count"]
        + result["review"]["model_review"]["market_summary"]["down_count"]
        + result["review"]["model_review"]["market_summary"]["flat_count"],
        "board_rows": len(result["review"]["mainlines"]),
        "role_rows": len(result["review"]["observation_pool"]),
        "close_chain_status": result["review"]["close_chain"]["status"],
        "publication": result["publication"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
