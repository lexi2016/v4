"""Generate D-1 fupan and Stage7 lanes for a target opening date.

These artifacts are pre-open inputs for the target date. They may only be
derived from the previous trading day's fupan outputs, never from the target
date's close, winners, or post-close validation.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ENCODING = "utf-8-sig"
V3_PREOPEN_LANE_ORACLE_SHA256 = "1176f6fe494ef7033bacb2fbbee4f09ce6c09d6c42515ec982dfd17eab6d4426"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

FIELDS = [
    "pool_rank",
    "target_date",
    "trade_date",
    "signal_date",
    "stage_id",
    "ts_code",
    "stock_code",
    "name",
    "stock_name",
    "display_name",
    "pool_type",
    "source_tag",
    "source_tags",
    "source_lanes",
    "stage7_group",
    "stage7_label",
    "stage7_next_day_pool_score",
    "pool_score",
    "primary_buy_signal",
    "secondary_buy_signal",
    "role",
    "theme",
    "route_context",
    "position_tags",
    "trigger_condition",
    "fail_condition",
    "boundary",
    "cannot_confirm",
    "source_trace",
]

SUMMARY_FIELDS = [
    "signal_date",
    "target_date",
    "theme",
    "stage7_group",
    "stock_count",
    "top_names",
    "basis",
    "boundary",
    "cannot_confirm",
]


def _previous_weekday(date8: str) -> str:
    cur = datetime.strptime(date8, "%Y%m%d").date() - timedelta(days=1)
    while cur.weekday() >= 5:
        cur -= timedelta(days=1)
    return cur.strftime("%Y%m%d")


def _signal_date(target_date: str, signal_date: str | None) -> str:
    return signal_date or _previous_weekday(target_date)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size <= 5:
        return []
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            payload = json.loads(path.read_text(encoding=encoding))
            return payload if isinstance(payload, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return {}


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    from domains._d1_review_lane_producer_parts.io_primitives import __write_csv_body as _v4_impl
    return _v4_impl(globals(), path, rows, fields)


def _write_json(path: Path, payload: object) -> None:
    from domains._d1_review_lane_producer_parts.io_primitives import __write_json_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _market_suffix(code: str) -> str:
    code = str(code or "").zfill(6)
    if code.startswith(("6", "9")):
        return ".SH"
    if code.startswith(("0", "2", "3")):
        return ".SZ"
    if code.startswith(("4", "8")):
        return ".BJ"
    return ""


def _clean_code(value: str) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError:
        return default


def _as_int(value: Any, default: int = 999999) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return default


def _role_score(role_type: str) -> int:
    scores = {
        "leader": 36,
        "capacity_anchor": 28,
        "rear_row": 12,
        "risk_anchor": -18,
    }
    return scores.get(str(role_type or ""), 0)


def _stage7_group(role_type: str, theme: str) -> tuple[str, str, int]:
    role_type = str(role_type or "")
    if role_type in {"leader", "capacity_anchor"}:
        return "明日分时优先观察", "D-1复盘前排/容量锚，次日必须看09:25-09:45承接。", 18
    if role_type == "rear_row":
        return "明日低优先级观察", "D-1复盘后排，只作触发器，不追后排冲高。", -6
    if role_type == "risk_anchor":
        return "明日强度锚点", "风险锚只用于看市场方向，不作为普通买入名单。", -16
    return "明日分时观察", f"{theme} 复盘角色待次日盘口确认。", 0


def _paths(
    target_date: str,
    signal_date: str,
    *,
    source_dir: Path,
    output_dir: Path,
    video_dir: Path | None,
) -> dict[str, Path]:
    from domains._d1_review_lane_producer_parts.io_primitives import __paths_body as _v4_impl
    return _v4_impl(globals(), target_date, signal_date, source_dir=source_dir, output_dir=output_dir, video_dir=video_dir)


def _source_paths(paths: dict[str, Path]) -> list[Path]:
    return [
        paths["anchor_role"],
        paths["theme_stocks"],
        paths["prior_plan"],
        paths["intraday_handoff"],
    ]


def _video_source_paths(paths: dict[str, Path]) -> list[Path]:
    return [
        paths["video_watch_status"],
        paths["video_acceptance"],
        paths["video_capture_manifest"],
        paths["video_gap_matrix"],
        paths["video_delta"],
    ]


def _first_text(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _load_video_fupan_context(paths: dict[str, Path], signal_date: str) -> dict[str, Any]:
    from domains._d1_review_lane_producer_parts.io_primitives import __load_video_fupan_context_body as _v4_impl
    return _v4_impl(globals(), paths, signal_date)


def _build_code_maps(theme_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    from domains._d1_review_lane_producer_parts.io_primitives import __build_code_maps_body as _v4_impl
    return _v4_impl(globals(), theme_rows)


def _build_video_fupan_rows(
    *,
    target_date: str,
    signal_date: str,
    video_context: dict[str, Any],
    code_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    from domains._d1_review_lane_producer_parts.io_primitives import __build_video_fupan_rows_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, signal_date=signal_date, video_context=video_context, code_map=code_map)


def _merge_fupan_and_video_rows(
    fupan_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from domains._d1_review_lane_producer_parts.io_primitives import __merge_fupan_and_video_rows_body as _v4_impl
    return _v4_impl(globals(), fupan_rows, video_rows)


def _build_rows(
    *,
    target_date: str,
    signal_date: str,
    paths: dict[str, Path],
    anchor_rows: list[dict[str, str]],
    theme_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    handoff_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    from domains._d1_review_lane_producer_parts.io_primitives import __build_rows_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, signal_date=signal_date, paths=paths, anchor_rows=anchor_rows, theme_rows=theme_rows, plan_rows=plan_rows, handoff_rows=handoff_rows)


def _build_summary(rows: list[dict[str, Any]], target_date: str, signal_date: str) -> list[dict[str, Any]]:
    from domains._d1_review_lane_producer_parts.io_primitives import __build_summary_body as _v4_impl
    return _v4_impl(globals(), rows, target_date, signal_date)


def _rows_for_lane(rows: list[dict[str, Any]], *, lane: str) -> list[dict[str, Any]]:
    from domains._d1_review_lane_producer_parts.lane_assembly import __rows_for_lane_body as _v4_impl
    return _v4_impl(globals(), rows, lane=lane)


def _build_real_stage7_rows(
    *,
    target_date: str,
    signal_date: str,
    path: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the Stage7 lane from the real D-1 14:45-15:00 replay output."""
    from domains._d1_review_lane_producer_parts.lane_assembly import __build_real_stage7_rows_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, signal_date=signal_date, path=path, manifest_path=manifest_path)


def ensure_preopen_lane_artifacts(
    target_date: str,
    *,
    signal_date: str | None = None,
    source_dir: Path,
    output_dir: Path,
    video_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure D-1 fupan and Stage7 lane CSVs exist for a target opening date."""
    from domains._d1_review_lane_producer_parts.preopen_lanes import _ensure_preopen_lane_artifacts_body as _v4_impl
    return _v4_impl(globals(), target_date, signal_date=signal_date, source_dir=source_dir, output_dir=output_dir, video_dir=video_dir, force=force)
