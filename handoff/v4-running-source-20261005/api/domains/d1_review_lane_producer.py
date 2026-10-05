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
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding=ENCODING, newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode(ENCODING)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    fupan_dir = Path(source_dir)
    preopen_dir = Path(output_dir)
    stage_data_dir = preopen_dir / "_stage7_evidence"
    video_watch_dir = Path(video_dir) if video_dir is not None else fupan_dir / "video"
    return {
        "fupan_dir": fupan_dir,
        "anchor_role": fupan_dir / "anchor_role.csv",
        "theme_stocks": fupan_dir / "theme_stocks.csv",
        "prior_plan": fupan_dir / "prior_plan.csv",
        "intraday_handoff": fupan_dir / "intraday_handoff.csv",
        "video_watch_status": video_watch_dir / "status.json",
        "video_acceptance": video_watch_dir / f"acceptance_{signal_date}.json",
        "video_capture_manifest": video_watch_dir / f"capture_manifest_{signal_date}.json",
        "video_gap_matrix": video_watch_dir / f"video_gap_matrix_{signal_date}.csv",
        "video_delta": video_watch_dir / f"new_video_delta_{signal_date}.csv",
        "fupan_pool": preopen_dir / "fupan.csv",
        "fupan_manifest": preopen_dir / "fupan.manifest.json",
        "stage7_preopen_pool": preopen_dir / "stage7.csv",
        "stage7_next_pool": stage_data_dir / f"{signal_date}_stage7_next_intraday_pool.csv",
        "stage7_intraday_pool": stage_data_dir / f"{target_date}_intraday_selection_pool_from_{signal_date}_stage7.csv",
        "stage7_summary": stage_data_dir / f"{signal_date}_stage7_1500_summary.csv",
        "stage7_manifest": preopen_dir / "stage7.manifest.json",
        "real_stage7_pool": fupan_dir / "stage7_tail_replay.csv",
        "real_stage7_manifest": fupan_dir / "stage7_tail_replay.manifest.json",
    }


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
    status_payload = _read_json(paths["video_watch_status"])
    if str(status_payload.get("trade_date") or "") != signal_date:
        status_payload = {}
    acceptance_payload = _read_json(paths["video_acceptance"])
    manifest_payload = _read_json(paths["video_capture_manifest"])
    gap_rows = _read_csv(paths["video_gap_matrix"])
    source_paths = [str(path) for path in _video_source_paths(paths) if path.exists()]

    status = (
        str(status_payload.get("status") or "")
        or str(acceptance_payload.get("status") or "")
        or str(manifest_payload.get("status") or "")
        or "VIDEO_FUPAN_POOL_NOT_READY"
    )
    videos = status_payload.get("videos") if isinstance(status_payload.get("videos"), list) else []
    if not videos and isinstance(acceptance_payload.get("videos"), list):
        videos = acceptance_payload.get("videos") or []
    def is_same_day_video(video: dict[str, Any]) -> bool:
        scope = str(video.get("date_scope") or "")
        upload_digits = "".join(ch for ch in str(video.get("upload_date") or "") if ch.isdigit())
        upload_date = upload_digits[:8] if len(upload_digits) >= 8 else ""
        return scope == "SAME_DAY_FUPAN" or upload_date == signal_date or (not scope and not upload_date)

    same_day_videos = [video for video in videos if isinstance(video, dict) and is_same_day_video(video)]

    cannot_confirm: list[str] = []
    for payload in (status_payload, acceptance_payload, manifest_payload):
        items = payload.get("cannot_confirm")
        if isinstance(items, list):
            cannot_confirm.extend(str(item) for item in items if str(item or "").strip())
    cannot_confirm = list(dict.fromkeys(cannot_confirm))
    if videos and not same_day_videos:
        if gap_rows:
            cannot_confirm.append(
                "Bilibili watch captured a latest fupan video, but it is not SAME_DAY_FUPAN for this signal date; "
                "video gap rows are kept for learning/audit and are not merged into the preopen fupan lane."
            )
        gap_rows = []

    if gap_rows and same_day_videos:
        video_pool_status = "VIDEO_FUPAN_GAP_MATRIX_READY"
    elif gap_rows:
        video_pool_status = "VIDEO_FUPAN_GAP_MATRIX_READY_VIDEO_META_PARTIAL"
    elif videos and not same_day_videos:
        video_pool_status = "VIDEO_FUPAN_CAPTURED_NOT_SIGNAL_DATE"
    elif status == "NO_NEW_VIDEO":
        video_pool_status = "VIDEO_FUPAN_NO_NEW_VIDEO"
    elif status == "BLOCKED_NEED_USER_COOKIE_OR_BV":
        video_pool_status = "VIDEO_FUPAN_BLOCKED_NEED_USER_COOKIE_OR_BV"
    else:
        video_pool_status = "VIDEO_FUPAN_POOL_NOT_READY"

    if not cannot_confirm and not gap_rows:
        cannot_confirm.append("D-1 video second-review did not produce a stock-level gap matrix for the preopen fupan pool.")

    return {
        "status": video_pool_status,
        "raw_status": status,
        "gap_rows": gap_rows,
        "videos_count": len(videos),
        "same_day_videos_count": len(same_day_videos),
        "source_paths": source_paths,
        "cannot_confirm": cannot_confirm,
    }


def _build_code_maps(theme_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for row in theme_rows:
        name = str(row.get("name") or "").strip()
        code = str(row.get("code") or "").strip().zfill(6)
        if not name or not code:
            continue
        mapping[name] = {
            "stock_code": code,
            "ts_code": f"{code}{_market_suffix(code)}",
        }
    return mapping


def _build_video_fupan_rows(
    *,
    target_date: str,
    signal_date: str,
    video_context: dict[str, Any],
    code_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_trace = " | ".join(video_context.get("source_paths") or [])
    blocked_decisions = {"REJECT", "NO_ACTION", "BLOCKED"}

    for raw in video_context.get("gap_rows") or []:
        if not isinstance(raw, dict):
            continue
        decision = _first_text(raw, "decision", "status").upper()
        if decision in blocked_decisions:
            continue

        ts_code = _first_text(raw, "ts_code")
        code = _clean_code(ts_code or _first_text(raw, "stock_code", "code", "symbol"))
        name = _first_text(raw, "stock_name", "name", "stock")
        if not code and name in code_map:
            info = code_map[name]
            code = info["stock_code"]
            ts_code = info["ts_code"]
        if not code:
            continue
        if not ts_code:
            ts_code = f"{code}{_market_suffix(code)}"
        if not name:
            name = code
        if code in seen:
            continue
        seen.add(code)

        route_context = "；".join(
            part
            for part in [
                _first_text(raw, "video_question_or_framework", "video_framework", "title_or_segment", "item"),
                _first_text(raw, "local_review_answer", "impact", "reason"),
            ]
            if part
        )
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_FUPAN_VIDEO_REVIEW",
                "ts_code": ts_code,
                "stock_code": code,
                "name": name,
                "stock_name": name,
                "display_name": f"{name}（复/视）",
                "pool_type": "D_MINUS_1_FUPAN_VIDEO_SECOND_REVIEW_POOL",
                "source_tag": "D1_FUPAN_VIDEO",
                "source_tags": "（复/视）",
                "source_lanes": "fupan_lane",
                "stage7_group": "视频二次复盘观察",
                "stage7_label": "D-1自动复盘后经视频二次复盘补充，目标日仍需竞价和开盘承接确认。",
                "stage7_next_day_pool_score": 58,
                "pool_score": 58,
                "primary_buy_signal": "0",
                "secondary_buy_signal": "0",
                "role": _first_text(raw, "role", "gap_type") or "video_second_review",
                "theme": _first_text(raw, "theme", "board", "item", "gap_type"),
                "route_context": route_context,
                "position_tags": f"video_second_review; decision={decision or 'UNKNOWN'}",
                "trigger_condition": _first_text(raw, "trigger_condition")
                or "目标日只看09:25-09:45承接、板块反馈和风险锚变化，不因视频复盘直接买入。",
                "fail_condition": _first_text(raw, "fail_condition")
                or "视频涉及股票无法被本地价量/开盘承接验证时降级为观察或剔除。",
                "boundary": "视频二次复盘只用于补充复盘观察池和风险校正，不是BUY gate。",
                "cannot_confirm": _first_text(raw, "cannot_confirm")
                or "视频股票名/观点仍需本地价量、ASR抽查和开盘承接确认。",
                "source_trace": source_trace,
            }
        )
    return rows


def _merge_fupan_and_video_rows(
    fupan_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    for row in fupan_rows:
        item = dict(row)
        code = str(item.get("stock_code") or _clean_code(item.get("ts_code", "")))
        if code:
            by_code[code] = item
        merged.append(item)

    for row in video_rows:
        code = str(row.get("stock_code") or _clean_code(row.get("ts_code", "")))
        existing = by_code.get(code)
        if existing is None:
            item = dict(row)
            by_code[code] = item
            merged.append(item)
            continue
        existing["source_tag"] = "D1_FUPAN+VIDEO"
        existing["source_tags"] = "（复/视）"
        existing["position_tags"] = f"{existing.get('position_tags', '')}; video_second_review"
        existing["route_context"] = f"{existing.get('route_context', '')} | video_second_review: {row.get('route_context', '')}"
        existing["source_trace"] = f"{existing.get('source_trace', '')} | {row.get('source_trace', '')}"
        existing["cannot_confirm"] = (
            f"{existing.get('cannot_confirm', '')}；视频二次复盘只作框架/风险校正，仍需目标日盘口确认。"
        )
        existing["pool_score"] = _as_float(existing.get("pool_score")) + 8
        existing["stage7_next_day_pool_score"] = existing["pool_score"]

    merged.sort(key=lambda item: (-_as_float(item.get("pool_score")), str(item.get("theme") or ""), str(item.get("stock_name") or "")))
    for idx, row in enumerate(merged, start=1):
        row["pool_rank"] = idx
    return merged


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
    code_map = _build_code_maps(theme_rows)
    plan_by_theme = {row.get("mapped_theme") or row.get("planned_anchor") or "": row for row in plan_rows}
    handoff_by_theme = {row.get("theme") or "": row for row in handoff_rows}
    source_trace = "；".join(str(path) for path in _source_paths(paths))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in anchor_rows:
        stock = str(raw.get("stock") or "").strip()
        theme = str(raw.get("theme") or "").strip()
        if not stock or stock in seen:
            continue
        info = code_map.get(stock)
        if not info:
            continue
        seen.add(stock)
        role_type = str(raw.get("role_type") or "")
        group, label, group_score = _stage7_group(role_type, theme)
        plan = plan_by_theme.get(theme, {})
        handoff = handoff_by_theme.get(theme, {})
        score = 50 + _role_score(role_type) + group_score
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_FUPAN_STAGE7",
                "ts_code": info["ts_code"],
                "stock_code": info["stock_code"],
                "name": stock,
                "stock_name": stock,
                "display_name": f"{stock}（复/分）",
                "pool_type": "D_MINUS_1_FUPAN_AND_STAGE7_OBSERVATION_POOL",
                "source_tag": "D1_FUPAN_STAGE7",
                "source_tags": "D1_FUPAN_STAGE7",
                "source_lanes": "fupan_lane / stage7_lane",
                "stage7_group": group,
                "stage7_label": label,
                "stage7_next_day_pool_score": score,
                "pool_score": score,
                "primary_buy_signal": "0",
                "secondary_buy_signal": "1" if role_type in {"leader", "capacity_anchor"} else "0",
                "role": role_type,
                "theme": theme,
                "route_context": str(raw.get("why_this_role") or ""),
                "position_tags": f"{role_type}; {group}; {handoff.get('close_role', '')}",
                "trigger_condition": str(
                    raw.get("tomorrow_if_strong")
                    or plan.get("tomorrow_scenario")
                    or "次日看09:25-09:45承接。"
                ),
                "fail_condition": str(raw.get("tomorrow_if_weak") or "容量锚或前排负反馈则降级。"),
                "boundary": "D-1复盘/Stage7观察池，不是买入名单；目标日必须再看竞价和开盘四阶段。",
                "cannot_confirm": str(raw.get("cannot_confirm") or "未确认L2/十档/逐笔/撤单/未匹配量。"),
                "source_trace": source_trace,
            }
        )

    rows.sort(key=lambda row: (-float(row["pool_score"]), row["theme"], row["stock_name"]))
    for idx, row in enumerate(rows, start=1):
        row["pool_rank"] = idx
    return rows


def _build_summary(rows: list[dict[str, Any]], target_date: str, signal_date: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["theme"]), str(row["stage7_group"]))].append(row)

    summary: list[dict[str, Any]] = []
    for (theme, group), items in sorted(grouped.items()):
        summary.append(
            {
                "signal_date": signal_date,
                "target_date": target_date,
                "theme": theme,
                "stage7_group": group,
                "stock_count": len(items),
                "top_names": "、".join(str(item["stock_name"]) for item in items[:8]),
                "basis": f"由{signal_date}复盘角色表、情景树和盘中交接表蒸馏生成。",
                "boundary": f"只作为{target_date}分时观察触发器，不是买入名单。",
                "cannot_confirm": "未确认结构化L2/十档/逐笔/撤单/未匹配量。",
            }
        )
    return summary


def _rows_for_lane(rows: list[dict[str, Any]], *, lane: str) -> list[dict[str, Any]]:
    tag = "（复）" if lane == "fupan_lane" else "（分）"
    label = "D1_FUPAN" if lane == "fupan_lane" else "D1_STAGE7"
    stage_id = "D_MINUS_1_FUPAN" if lane == "fupan_lane" else "D_MINUS_1_STAGE7"
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["stage_id"] = stage_id
        item["display_name"] = f"{item.get('stock_name') or item.get('name')}{tag}"
        item["source_tag"] = label
        item["source_tags"] = tag
        item["source_lanes"] = lane
        item["pool_type"] = (
            "D_MINUS_1_FUPAN_OBSERVATION_POOL"
            if lane == "fupan_lane"
            else "D_MINUS_1_STAGE7_NEXT_INTRADAY_POOL"
        )
        out.append(item)
    return out


def _build_real_stage7_rows(
    *,
    target_date: str,
    signal_date: str,
    path: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the Stage7 lane from the real D-1 14:45-15:00 replay output."""

    raw_rows = _read_csv(path)
    manifest = _read_json(manifest_path)
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        code = _clean_code(
            raw.get("stock_code") or raw.get("code") or raw.get("ts_code", "")
        )
        name = str(raw.get("name") or raw.get("stock_name") or raw.get("display_name") or code).strip()
        if not code or not name:
            continue
        ts_code = f"{code}{_market_suffix(code)}"
        score = _as_float(raw.get("stage_score") or raw.get("pool_score"))
        source_path = str(raw.get("source_path") or "")
        source_trace = str(path)
        if source_path:
            source_trace = f"{source_trace} | replay_source={source_path}"
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_REAL_STAGE7_TAIL_REPLAY",
                "ts_code": ts_code,
                "stock_code": code,
                "name": name,
                "stock_name": name,
                "display_name": f"{name}（分）",
                "pool_type": "D_MINUS_1_STAGE7_NEXT_INTRADAY_POOL",
                "source_tag": "D1_REAL_STAGE7",
                "source_tags": "（分）",
                "source_lanes": "stage7_lane",
                "stage7_group": str(raw.get("stage7_label") or raw.get("stage") or "D-1 Stage7 尾盘观察"),
                "stage7_label": str(raw.get("stage7_label") or raw.get("stage_note") or ""),
                "stage7_next_day_pool_score": f"{score:.2f}",
                "pool_score": f"{score:.2f}",
                "primary_buy_signal": str(raw.get("primary_buy_signal") or "0"),
                "secondary_buy_signal": str(raw.get("secondary_buy_signal") or "0"),
                "role": str(raw.get("stage7_label") or "D-1 Stage7尾盘"),
                "theme": "",
                "route_context": str(raw.get("stage_note") or ""),
                "position_tags": f"stage7_rank={raw.get('stage7_rank') or raw.get('pool_rank') or ''}; window={raw.get('window') or raw.get('bar_window') or ''}",
                "trigger_condition": "目标日仅看 09:25-09:45 分时承接、竞价强弱和板块反馈；不因 D-1 尾盘池直接买入。",
                "fail_condition": "目标日竞价低于预期、开盘无承接、放量下杀或板块负反馈则降级。",
                "boundary": "D-1 14:45-15:00 本地 1 分钟线尾盘回放，只作次日分时观察触发器，不是买入名单。",
                "cannot_confirm": str(
                    raw.get("cannot_confirm")
                    or "仅为本地历史 1 分钟 K 线回放，不能确认逐笔主动买卖、十档队列、撤单轨迹、竞价未匹配量。"
                ),
                "source_trace": source_trace,
                "_sort_rank": _as_int(raw.get("stage7_rank") or raw.get("pool_rank")),
                "_sort_score": score,
            }
        )

    rows.sort(key=lambda row: (int(row.get("_sort_rank") or 999999), -float(row.get("_sort_score") or 0), row["stock_code"]))
    for idx, row in enumerate(rows, start=1):
        row["pool_rank"] = idx
        row.pop("_sort_rank", None)
        row.pop("_sort_score", None)

    return rows, manifest


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

    signal = _signal_date(target_date, signal_date)
    paths = _paths(
        target_date,
        signal,
        source_dir=Path(source_dir),
        output_dir=Path(output_dir),
        video_dir=Path(video_dir) if video_dir is not None else None,
    )
    output_paths = [
        paths["fupan_pool"],
        paths["stage7_preopen_pool"],
        paths["stage7_next_pool"],
        paths["stage7_intraday_pool"],
        paths["stage7_summary"],
        paths["fupan_manifest"],
        paths["stage7_manifest"],
    ]
    real_stage7_available = bool(paths["real_stage7_pool"].exists() and _read_csv(paths["real_stage7_pool"]))
    if not force and all(path.exists() and path.stat().st_size > 5 for path in output_paths):
        fupan_manifest = _read_json(paths["fupan_manifest"])
        stage7_manifest = _read_json(paths["stage7_manifest"])
        if fupan_manifest.get("fupan_pool_rule") != "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW":
            force = True
        elif real_stage7_available and stage7_manifest.get("source_role") != "real_d1_stage7_tail_replay":
            force = True
        else:
            existing_rows = _read_csv(paths["fupan_pool"])
            return {
                "ok": True,
                "status": "PREOPEN_D1_LANES_READY_EXISTING",
                "target_date": target_date,
                "signal_date": signal,
                "row_count": len(existing_rows),
                "paths": {key: str(value) for key, value in paths.items() if key not in {"fupan_dir"}},
                "cannot_confirm": [],
            }

    missing = [path for path in _source_paths(paths) if not path.exists()]
    if missing:
        return {
            "ok": False,
            "status": "SKIPPED_MISSING_D1_FUPAN_EVIDENCE",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": 0,
            "missing_paths": [str(path) for path in missing],
            "cannot_confirm": [
                f"未找到 {signal} 的 D-1 复盘证据文件，不能生成 {target_date} 早盘复盘/Stage7 lane。",
                "不会使用目标日收盘结果、强势股榜或其他日期文件补位。",
            ],
        }

    anchor_rows = _read_csv(paths["anchor_role"])
    theme_rows = _read_csv(paths["theme_stocks"])
    plan_rows = _read_csv(paths["prior_plan"])
    handoff_rows = _read_csv(paths["intraday_handoff"])
    video_context = _load_video_fupan_context(paths, signal)
    rows = _build_rows(
        target_date=target_date,
        signal_date=signal,
        paths=paths,
        anchor_rows=anchor_rows,
        theme_rows=theme_rows,
        plan_rows=plan_rows,
        handoff_rows=handoff_rows,
    )
    if not rows:
        return {
            "ok": False,
            "status": "SKIPPED_EMPTY_D1_FUPAN_LANES",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": 0,
            "source_paths": [str(path) for path in _source_paths(paths)],
            "cannot_confirm": ["D-1 复盘证据存在，但没有可映射代码的观察行。"],
        }

    auto_fupan_rows = _rows_for_lane(rows, lane="fupan_lane")
    video_rows = _build_video_fupan_rows(
        target_date=target_date,
        signal_date=signal,
        video_context=video_context,
        code_map=_build_code_maps(theme_rows),
    )
    fupan_rows = _merge_fupan_and_video_rows(auto_fupan_rows, video_rows)
    real_stage7_manifest: dict[str, Any] = {}
    stage7_source_role = "synthetic_from_d1_fupan_role_table"
    if real_stage7_available:
        stage7_rows, real_stage7_manifest = _build_real_stage7_rows(
            target_date=target_date,
            signal_date=signal,
            path=paths["real_stage7_pool"],
            manifest_path=paths["real_stage7_manifest"],
        )
        if stage7_rows:
            stage7_source_role = "real_d1_stage7_tail_replay"
        else:
            stage7_rows = _rows_for_lane(rows, lane="stage7_lane")
    else:
        stage7_rows = _rows_for_lane(rows, lane="stage7_lane")
    _write_csv(paths["fupan_pool"], fupan_rows, FIELDS)
    _write_csv(paths["stage7_preopen_pool"], stage7_rows, FIELDS)
    _write_csv(paths["stage7_next_pool"], stage7_rows, FIELDS)
    _write_csv(paths["stage7_intraday_pool"], stage7_rows, FIELDS)
    _write_csv(paths["stage7_summary"], _build_summary(stage7_rows, target_date, signal), SUMMARY_FIELDS)

    cannot_confirm = [
        f"{target_date} 早盘复盘 lane 来自 {signal} 复盘结构化证据；Stage7 lane 优先来自 {signal} 14:45-15:00 尾盘 1 分钟回放。",
        "未确认L2/十档/逐笔委托/撤单/未匹配量；目标日仍必须看09:25-09:45承接。",
        "该 lane 不能替代正式 1.9.2/FMLA04 selector，只能作为辅助并源。",
    ]
    cannot_confirm.extend(video_context.get("cannot_confirm") or [])
    generated_at = datetime.now().isoformat(timespec="seconds")
    source_path_strings = [str(path) for path in _source_paths(paths)]
    all_source_path_strings = [*source_path_strings, *(video_context.get("source_paths") or [])]
    _write_json(
        paths["fupan_manifest"],
        {
            "status": "FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL",
            "fupan_pool_rule": "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": len(fupan_rows),
            "auto_fupan_row_count": len(auto_fupan_rows),
            "video_fupan_status": video_context.get("status"),
            "video_fupan_raw_status": video_context.get("raw_status"),
            "video_fupan_gap_rows": len(video_context.get("gap_rows") or []),
            "video_fupan_stock_rows_added": len(video_rows),
            "source_paths": all_source_path_strings,
            "auto_fupan_source_paths": source_path_strings,
            "video_source_paths": video_context.get("source_paths") or [],
            "pool_path": str(paths["fupan_pool"]),
            "generated_at": generated_at,
            "overlap_note": "This lane starts from automatic D-1 fupan, then consumes available Bilibili/video second-review gap rows; video-blocked runs stay explicit in video_fupan_status.",
            "cannot_confirm": cannot_confirm,
            **SAFETY,
        },
    )
    _write_json(
        paths["stage7_manifest"],
        {
            "status": "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
            "target_date": target_date,
            "signal_date": signal,
            "row_count": len(stage7_rows),
            "source_role": stage7_source_role,
            "source_paths": (
                [str(paths["real_stage7_pool"]), str(paths["real_stage7_manifest"])]
                if stage7_source_role == "real_d1_stage7_tail_replay"
                else source_path_strings
            ),
            "pool_paths": [
                str(paths["stage7_preopen_pool"]),
                str(paths["stage7_next_pool"]),
                str(paths["stage7_intraday_pool"]),
            ],
            "summary_path": str(paths["stage7_summary"]),
            "generated_at": generated_at,
            "upstream_manifest": real_stage7_manifest if stage7_source_role == "real_d1_stage7_tail_replay" else {},
            "overlap_note": (
                "Stage7 lane is generated from the real D-1 14:45-15:00 replay, so full equality with fupan lane is treated as a bug."
                if stage7_source_role == "real_d1_stage7_tail_replay"
                else "Fallback lane is distilled from D-1 fupan role evidence and must be treated as inferred, not real tail replay."
            ),
            "cannot_confirm": cannot_confirm,
            **SAFETY,
        },
    )

    return {
        "ok": True,
        "status": "PREOPEN_D1_LANES_READY",
        "target_date": target_date,
        "signal_date": signal,
        "row_count": len(fupan_rows),
        "stage7_row_count": len(stage7_rows),
        "stage7_source_role": stage7_source_role,
        "paths": {key: str(value) for key, value in paths.items() if key not in {"fupan_dir"}},
        "source_paths": all_source_path_strings,
        "video_fupan_status": video_context.get("status"),
        "video_fupan_stock_rows_added": len(video_rows),
        "cannot_confirm": cannot_confirm,
        **SAFETY,
    }


def materialize_recovered_stage7_lane(data_root: Path, *, signal_date: str = "20260917",
                                      target_date: str = "20260918", verify_only: bool = False) -> dict[str, Any]:
    """Bounded Stage7-only recovery; never synthesize the missing Fupan lane.

    Reuses both existing Stage7 transforms. The recovered input is read back
    through StageStore, and each derived file is immutable within this run.
    ``verify_only`` recomputes all four documents without writing or repairing.
    """
    import io
    from domains.d1_review_source_producer import _build_stage7_tail
    from infrastructure.data_store import _canonical_bytes
    from infrastructure.historical_pool_sources import (
        coverage, source_identity, verified_stage7_input,
    )
    from infrastructure.owned_io import SafeRoot
    root = Path(data_root)
    original, payload, input_sha = verified_stage7_input(root, signal_date, target_date)
    raw_sha = original["authority"]["artifact.csv"]
    c = coverage(signal_date, target_date)
    count = c["source_rows"]
    source_dir = root / "d1_review_sources" / signal_date / "historical_stage7" / raw_sha
    lane_dir = root / "d1_review_lanes" / target_date / "historical_stage7" / raw_sha
    paths = _paths(target_date, signal_date, source_dir=source_dir, output_dir=lane_dir, video_dir=None)
    owner = SafeRoot(root)
    def persist(path, data):
        relative = path.relative_to(root).as_posix()
        try:
            existing = owner.read_bytes(relative)
        except FileNotFoundError:
            if verify_only:
                raise ValueError("recovered Stage7 derived file is missing; verify-only cannot repair it")
            owner.write_bytes(relative, data)
        else:
            if existing != data:
                raise ValueError("conflicting recovered Stage7 derived file; do not overwrite dirty data")
    def csv_bytes(rows, fields):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])
        return stream.getvalue().encode(ENCODING)
    cannot = list(payload["cannot_confirm"]) + [
        "NO_HISTORICAL_STAGE_SCORE: original CSV order retained; zero lane scores are not model evidence",
        "RECOVERY_DERIVED_NOW_NOT_ORIGINAL_PRODUCER_ARTIFACT",
    ]
    tail = _build_stage7_tail({"STAGE_1445_1500": payload}, signal_date)
    if len(tail) != count:
        raise ValueError("Stage7 tail transform lost original rows")
    for row in tail:
        row["stage7_label"] = f"{signal_date[4:]} PyTDX HQ 原始{count}/{c['requested_rows']}尾盘行，逐行截止安全，覆盖不完整"
        row["source_path"] = f"stage_inputs/{signal_date}/STAGE_1445_1500.json"
        row["candidate_source_path"] = row["source_path"]
        row["cannot_confirm"] = "; ".join(cannot)
    upstream = {"trade_date": signal_date, "stage_id": "STAGE_1445_1500", "row_count": count,
                "status": "PARTIAL_WITH_ROWS", "source_id": "pytdx_hq",
                "stage_input_sha256": input_sha, "coverage_evidence": c,
                **source_identity(original), "cannot_confirm": cannot, **SAFETY}
    persist(paths["real_stage7_pool"], csv_bytes(tail, list(tail[0])))
    persist(paths["real_stage7_manifest"], _canonical_bytes(upstream))
    rows, checked_upstream = _build_real_stage7_rows(target_date=target_date, signal_date=signal_date,
                path=paths["real_stage7_pool"], manifest_path=paths["real_stage7_manifest"])
    if len(rows) != count or checked_upstream != upstream:
        raise ValueError("Stage7 lane transform lost original rows or provenance")
    manifest = {"status": "STAGE7_TAIL_POOL_READY_DATA_PARTIAL", "target_date": target_date,
        "signal_date": signal_date, "row_count": count, "source_role": "real_d1_stage7_tail_replay",
        "upstream_manifest": upstream, "source_paths": [str(paths["real_stage7_pool"]), str(paths["real_stage7_manifest"])],
        "coverage_evidence": c, "cannot_confirm": cannot, **SAFETY}
    persist(paths["stage7_preopen_pool"], csv_bytes(rows, FIELDS))
    persist(paths["stage7_manifest"], _canonical_bytes(manifest))
    # Other lanes and legacy secondary files are deliberately not fabricated.
    return {"status": "PARTIAL_WITH_ROWS", "lane_dir": str(lane_dir),
            "row_count": count, "coverage_evidence": c, "cannot_confirm": cannot, **SAFETY}
