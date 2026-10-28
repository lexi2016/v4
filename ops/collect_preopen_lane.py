"""V4 fupan/stage7 preopen lane collector.

Reads the V3 fupan page-complete raw CSVs (anchor roles, theme stocks,
prior plan, intraday handoff) and produces the A-share fupan-watchlist and
stage7 review pools using the same role/group scoring as the V3
preopen_lane_generator. Output CSVs are consumable by
preselection_materializer.build_upstream_csv_pool.

Nothing is written into V3; only the V3 raw artifacts are read.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

# Legacy V3 roots are injected via env (same var baimao/research lane use).
# The stage7/hk-overlay data products live under the 8771 runtime data dir.
V3_DEBUG_ROOT = Path(os.environ["V4_V3_DATA_ROOT"]) / "40_artifacts" / "runtime_debug" if os.environ.get("V4_V3_DATA_ROOT") else Path("")
_V3_RUNTIME_DATA = Path(os.environ["V4_V3_DATA_ROOT"]) / "30_runtime" / "opening_advisor_8771" / "data" if os.environ.get("V4_V3_DATA_ROOT") else Path("")


def _previous_weekday(date8: str) -> str:
    """Return the previous weekday (YYYYMMDD), stepping back over weekends."""
    import datetime
    date = datetime.datetime.strptime(date8, "%Y%m%d").date()
    while True:
        date -= datetime.timedelta(days=1)
        if date.weekday() < 5:
            return date.strftime("%Y%m%d")


def _signal_date(target_date: str, signal_date: str | None) -> str:
    return signal_date or _previous_weekday(target_date)


def _market_suffix(code: str) -> str:
    if code.startswith(("6", "5", "9", "688", "689")):
        return ".SH"
    return ".SZ"


def _role_score(role_type: str) -> int:
    scores = {"leader": 36, "capacity_anchor": 28, "rear_row": 12, "risk_anchor": -18}
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _clean_code(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_lane_rows(
    *,
    target_date: str,
    signal_date: str,
    fupan_dir: Path,
) -> list[dict[str, Any]]:
    anchor_rows = _read_csv(fupan_dir / f"anchor_role_v3_table_{signal_date}.csv")
    theme_rows = _read_csv(fupan_dir / f"duanxianxia_theme_stock_rows_{signal_date}.csv")
    plan_rows = _read_csv(fupan_dir / f"prior_plan_validation_{signal_date}.csv")
    handoff_rows = _read_csv(fupan_dir / f"intraday_handoff_{signal_date}.csv")

    code_map: dict[str, dict[str, str]] = {}
    for row in theme_rows:
        name = str(row.get("name") or "").strip()
        code = _clean_code(row.get("code"))
        if not name or not code:
            continue
        code_map[name] = {"stock_code": code, "ts_code": f"{code}{_market_suffix(code)}"}

    plan_by_theme = {str(row.get("mapped_theme") or row.get("planned_anchor") or ""): row for row in plan_rows}
    handoff_by_theme = {str(row.get("theme") or ""): row for row in handoff_rows}

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
        rows.append({
            "target_date": target_date,
            "trade_date": target_date,
            "signal_date": signal_date,
            "stage_id": "D_MINUS_1_FUPAN_STAGE7",
            "ts_code": info["ts_code"],
            "stock_code": info["stock_code"],
            "stock_name": stock,
            "pool_rank": len(rows) + 1,
            "pool_score": score,
            "role_type": role_type,
            "stage7_group": group,
            "stage7_label": label,
            "theme": theme,
            "source_lanes": "fupan_lane / stage7_lane",
            "primary_buy_signal": str(plan.get("primary_buy_signal") or ""),
            "secondary_buy_signal": str(plan.get("secondary_buy_signal") or ""),
            "plan_validation": str(plan.get("validation") or ""),
            "handoff": str(handoff.get("handoff") or ""),
        })
    return rows


def write_pool_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_stage7_rows(
    *,
    target_date: str,
    signal_date: str,
    replay_csv: Path,
) -> list[dict[str, Any]]:
    """Read the V3 generated stage7 tail-replay CSV into v3.5 stage7 pool rows."""
    raw_rows = _read_csv(replay_csv)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        ts_code = str(raw.get("ts_code") or "").strip()
        if not ts_code:
            continue
        score = _as_float(raw.get("stage_score") or raw.get("pool_score"))
        rows.append({
            "target_date": target_date,
            "trade_date": target_date,
            "signal_date": signal_date,
            "stage_id": "D_MINUS_1_REAL_STAGE7_TAIL_REPLAY",
            "ts_code": ts_code,
            "stock_code": ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", ""),
            "stock_name": str(raw.get("name") or "").strip(),
            "pool_rank": int(raw.get("stage7_rank") or index),
            "pool_score": score,
            "stage7_next_day_pool_score": score,
            "stage7_group": str(raw.get("stage7_label") or "").strip(),
            "stage7_label": str(raw.get("stage7_label") or "").strip(),
            "window": str(raw.get("window") or "").strip(),
            "window_change_pct": str(raw.get("window_change_pct") or "").strip(),
            "source_lanes": "stage7_lane",
            "primary_buy_signal": str(raw.get("primary_buy_signal") or ""),
            "secondary_buy_signal": str(raw.get("secondary_buy_signal") or ""),
        })
    rows.sort(key=lambda r: -r["pool_score"])
    return rows


def build_hk_rows(
    *,
    target_date: str,
    overlay_csv: Path,
) -> list[dict[str, Any]]:
    """Read the V3 hkconnect a-overlay pool CSV into v3.5 HK D-1 pool rows."""
    raw_rows = _read_csv(overlay_csv)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        code = str(raw.get("code") or raw.get("code_norm") or "").upper()
        match = re.search(r"(\d{5})", code)
        if not match:
            continue
        symbol = f"HK.{match.group(1)}"
        rows.append({
            "symbol": symbol,
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": int(raw.get("rank") or index),
            "stock_name": str(raw.get("name") or symbol),
            "pool_score": _as_float(raw.get("score_prob_active") or raw.get("hybrid_score")),
            "target_date": target_date,
            "signal_date": str(raw.get("signal_date") or ""),
            "selected_strategy": str(raw.get("selected_strategy") or ""),
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    rows.sort(key=lambda r: -r["pool_score"])
    return rows


def build_wechat_rows(
    *,
    target_date: str,
    manifest_path: Path,
    rows_csv: Path,
) -> list[dict[str, Any]]:
    """Read the V3 WeChat manifest + rows CSV into v3.5 wechat pool rows."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("status") != "WECHAT_V3_PRESELECT_READY":
        return []
    raw_rows = _read_csv(rows_csv)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        code = str(raw.get("ts_code") or raw.get("code") or "").strip().zfill(6)
        if not code:
            continue
        rows.append({
            "target_date": target_date,
            "trade_date": target_date,
            "ts_code": code,
            "stock_code": code,
            "stock_name": str(raw.get("wechat_name") or raw.get("name") or code),
            "pool_rank": index,
            "pool_score": _as_float(raw.get("candidate_score") or raw.get("wechat_hit_count")),
            "wechat_hit_count": str(raw.get("wechat_hit_count") or ""),
            "wechat_theme": str(raw.get("wechat_theme") or ""),
            "wechat_source_ref": str(raw.get("wechat_source_ref") or ""),
            "guard_pass": str(raw.get("guard_pass") or ""),
            "source_lanes": "wechat_lane",
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    return rows


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Collect fupan/stage7 preopen lane pools")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--signal-date", default=None)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stage7-replay", type=Path, default=None)
    parser.add_argument("--hk-overlay", type=Path, default=None)
    parser.add_argument("--wechat-manifest", type=Path, default=None)
    parser.add_argument("--wechat-rows", type=Path, default=None)
    parser.add_argument("--v3-debug-root", type=Path, default=V3_DEBUG_ROOT)
    parser.add_argument("--v3-stage7-root", type=Path, default=_V3_RUNTIME_DATA / "generated_stages")
    parser.add_argument("--v3-hk-overlay-root", type=Path, default=_V3_RUNTIME_DATA / "hkconnect_a_overlay_pools")
    args = parser.parse_args()

    signal_date = _signal_date(args.target_date, args.signal_date)
    fupan_dir = args.v3_debug_root / f"{signal_date}_fupan_page_complete"
    rows = build_lane_rows(target_date=args.target_date, signal_date=signal_date, fupan_dir=fupan_dir)
    write_pool_csv(args.output, rows)
    result = {
        "target_date": args.target_date,
        "signal_date": signal_date,
        "fupan_dir": str(fupan_dir),
        "fupan_rows": len(rows),
        "output": str(args.output),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if args.stage7_replay is not None:
        stage7 = build_stage7_rows(target_date=args.target_date, signal_date=signal_date, replay_csv=args.stage7_replay)
        write_pool_csv(args.output.with_name(args.output.stem + "_stage7.csv"), stage7)
        result["stage7_replay"] = str(args.stage7_replay)
        result["stage7_rows"] = len(stage7)
    elif args.v3_stage7_root is not None:
        replay = args.v3_stage7_root / signal_date / f"generated_stage7_1445_1500_1min_replay_{signal_date}.csv"
        if replay.is_file():
            stage7 = build_stage7_rows(target_date=args.target_date, signal_date=signal_date, replay_csv=replay)
            write_pool_csv(args.output.with_name(args.output.stem + "_stage7.csv"), stage7)
            result["stage7_replay"] = str(replay)
            result["stage7_rows"] = len(stage7)
        else:
            result["stage7_replay"] = str(replay)
            result["stage7_rows"] = 0
            result["stage7_note"] = "replay CSV not found"
    if args.hk_overlay is not None:
        hk_rows = build_hk_rows(target_date=args.target_date, overlay_csv=args.hk_overlay)
        write_pool_csv(args.output.with_name(args.output.stem + "_hk.csv"), hk_rows)
        result["hk_overlay"] = str(args.hk_overlay)
        result["hk_rows"] = len(hk_rows)
    elif args.v3_hk_overlay_root is not None:
        overlay = args.v3_hk_overlay_root / args.target_date / f"hkconnect_a_overlay_pool_{args.target_date}.csv"
        if overlay.is_file():
            hk_rows = build_hk_rows(target_date=args.target_date, overlay_csv=overlay)
            write_pool_csv(args.output.with_name(args.output.stem + "_hk.csv"), hk_rows)
            result["hk_overlay"] = str(overlay)
            result["hk_rows"] = len(hk_rows)
        else:
            result["hk_overlay"] = str(overlay)
            result["hk_rows"] = 0
            result["hk_note"] = "overlay CSV not found"
    if args.wechat_manifest is not None and args.wechat_rows is not None:
        wechat = build_wechat_rows(target_date=args.target_date, manifest_path=args.wechat_manifest, rows_csv=args.wechat_rows)
        write_pool_csv(args.output.with_name(args.output.stem + "_wechat.csv"), wechat)
        result["wechat_manifest"] = str(args.wechat_manifest)
        result["wechat_rows"] = len(wechat)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
