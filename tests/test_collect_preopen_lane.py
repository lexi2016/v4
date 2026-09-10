"""Tests for the V3.5 fupan/stage7 preopen lane collector."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ops.collect_preopen_lane import build_hk_rows, build_lane_rows, build_stage7_rows, build_wechat_rows, write_pool_csv


def _write_fupan_snapshot(root: Path, signal_date: str) -> Path:
    fupan_dir = root / f"{signal_date}_fupan_page_complete"
    fupan_dir.mkdir(parents=True, exist_ok=True)
    (fupan_dir / f"anchor_role_v3_table_{signal_date}.csv").write_text(
        "stock,theme,role_type\n"
        "中材国际,一带一路,leader\n"
        "比亚迪,新能源,capacity_anchor\n"
        "传智教育,教育,rear_row\n"
        "风险股,风险板块,risk_anchor\n",
        encoding="utf-8",
    )
    (fupan_dir / f"duanxianxia_theme_stock_rows_{signal_date}.csv").write_text(
        "name,code\n"
        "中材国际,600970\n"
        "比亚迪,002594\n"
        "传智教育,003032\n"
        "风险股,000001\n",
        encoding="utf-8",
    )
    (fupan_dir / f"prior_plan_validation_{signal_date}.csv").write_text(
        "mapped_theme,validation,primary_buy_signal,secondary_buy_signal\n"
        "一带一路,ok,首日承接,回踩确认\n",
        encoding="utf-8",
    )
    (fupan_dir / f"intraday_handoff_{signal_date}.csv").write_text(
        "theme,handoff\n一带一路,次日观察\n",
        encoding="utf-8",
    )
    return fupan_dir


def test_build_lane_rows_scores_roles(tmp_path: Path) -> None:
    fupan_dir = _write_fupan_snapshot(tmp_path, "20260729")
    rows = build_lane_rows(target_date="20260730", signal_date="20260729", fupan_dir=fupan_dir)
    assert len(rows) == 4
    by_name = {row["stock_name"]: row for row in rows}
    # leader: 50 + 36 + 18 = 104, stage7_group 明日分时优先观察
    assert by_name["中材国际"]["pool_score"] == 104
    assert by_name["中材国际"]["stage7_group"] == "明日分时优先观察"
    # capacity_anchor: 50 + 28 + 18 = 96
    assert by_name["比亚迪"]["pool_score"] == 96
    # rear_row: 50 + 12 - 6 = 56
    assert by_name["传智教育"]["pool_score"] == 56
    assert by_name["传智教育"]["stage7_group"] == "明日低优先级观察"
    # risk_anchor: 50 - 18 - 16 = 16
    assert by_name["风险股"]["pool_score"] == 16
    assert by_name["风险股"]["stage7_group"] == "明日强度锚点"
    # ts_code mapping
    assert by_name["中材国际"]["ts_code"] == "600970.SH"
    assert by_name["比亚迪"]["ts_code"] == "002594.SZ"


def test_write_pool_csv_roundtrip(tmp_path: Path) -> None:
    fupan_dir = _write_fupan_snapshot(tmp_path, "20260729")
    rows = build_lane_rows(target_date="20260730", signal_date="20260729", fupan_dir=fupan_dir)
    out = tmp_path / "pool.csv"
    write_pool_csv(out, rows)
    with out.open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert len(written) == 4
    assert written[0]["target_date"] == "20260730"
    assert written[0]["ts_code"] == "600970.SH"


def test_empty_input_writes_empty(tmp_path: Path) -> None:
    empty_dir = tmp_path / "20260730_fupan_page_complete"
    empty_dir.mkdir(parents=True, exist_ok=True)
    rows = build_lane_rows(target_date="20260731", signal_date="20260730", fupan_dir=empty_dir)
    assert rows == []
    out = tmp_path / "empty.csv"
    write_pool_csv(out, rows)
    assert out.read_text(encoding="utf-8") == ""


def test_build_stage7_rows_scores(tmp_path: Path) -> None:
    replay = tmp_path / "replay.csv"
    replay.write_text(
        "pool_rank,ts_code,name,stage_score,stage7_rank,window,stage7_label,primary_buy_signal,secondary_buy_signal\n"
        "1,600970.SH,中材国际,114.02,2,14:45-15:00,阶段转强,首日承接,\n"
        "2,002594.SZ,比亚迪,96.5,1,14:45-15:00,阶段承接,,回踩确认\n",
        encoding="utf-8",
    )
    rows = build_stage7_rows(target_date="20260730", signal_date="20260729", replay_csv=replay)
    # sorted by score desc: 中材国际(114.02) first
    assert len(rows) == 2
    assert rows[0]["ts_code"] == "600970.SH"
    assert rows[0]["pool_score"] == 114.02
    assert rows[0]["pool_rank"] == 2  # stage7_rank
    assert rows[0]["stock_code"] == "600970"
    assert rows[1]["ts_code"] == "002594.SZ"
    assert rows[1]["pool_score"] == 96.5


def test_build_hk_rows_scores(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.csv"
    overlay.write_text(
        "rank,code,name,score_prob_active,signal_date,selected_strategy\n"
        "1,00325,华润啤酒,0.83,20260729,prob_active\n"
        "2,00700,腾讯控股,0.78,20260729,prob_active\n",
        encoding="utf-8",
    )
    rows = build_hk_rows(target_date="20260730", overlay_csv=overlay)
    assert len(rows) == 2
    assert rows[0]["symbol"] == "HK.00325"
    assert rows[0]["pool_score"] == 0.83
    assert rows[1]["symbol"] == "HK.00700"
    assert rows[1]["pool_rank"] == 2


def test_build_wechat_rows(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "status": "WECHAT_V3_PRESELECT_READY",
        "signal_date": "20260729",
        "target_date": "20260730",
        "effective_trade_date": "20260730",
        "counts": {"v3_matched_codes": 2},
    }), encoding="utf-8")
    rows_csv = tmp_path / "rows.csv"
    rows_csv.write_text(
        "ts_code,code,wechat_name,wechat_hit_count,wechat_theme,guard_pass,candidate_score\n"
        "600298.SH,600298,安琪酵母,1,微信观察,pass,5.5\n"
        "603288.SH,603288,海天味业,2,微信观察,pass,4.0\n",
        encoding="utf-8",
    )
    rows = build_wechat_rows(target_date="20260730", manifest_path=manifest, rows_csv=rows_csv)
    assert len(rows) == 2
    assert rows[0]["ts_code"] == "600298.SH"
    assert rows[0]["stock_name"] == "安琪酵母"
    assert rows[0]["pool_score"] == 5.5


def test_build_wechat_rows_rejects_bad_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"status": "OTHER"}), encoding="utf-8")
    rows_csv = tmp_path / "rows.csv"
    rows_csv.write_text("ts_code,name\n600298.SH,安琪酵母\n", encoding="utf-8")
    assert build_wechat_rows(target_date="20260730", manifest_path=manifest, rows_csv=rows_csv) == []
