from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.preselection_materializer import build_baimao_pool, build_wechat_pool
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore


NAMES = {
    "a_d1_premarket_pool": "A股 D-1 主预选池",
    "a_d1_fupan_watchlist_pool": "A股 D-1 复盘继续观察池",
    "a_d1_stage7_fenshi_review_pool": "A股 D-1 Stage7/分时复盘池",
    "a_share_research_recommendation_pool": "A股研报推荐股票池",
    "a_share_baimao_research_map": "白毛卡点研究池",
    "hkconnect_d1_top100": "港股通 0.2 D-1 Top100",
    "wechat_public_account_v3_preselect": "公众号股票池",
}


def _artifact(pool_id: str, count: int, date: str = "20260731") -> dict:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    rows = [
        {
            "symbol": f"HK.{index:05d}" if market == "HK" else f"A.{index:06d}",
            "market": market,
            "pool_id": pool_id,
            "pool_rank": index,
            "recommendation_status": "WATCH_ONLY",
        }
        for index in range(1, count + 1)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": pool_id,
        "display_name": NAMES[pool_id],
        "market": market,
        "status": "CANNOT_CONFIRM" if count == 0 else "available",
        "producer_id": "task5_test_producer",
        "source_role": "EXPECTED_MISSING" if count == 0 else "RAW_SOURCE",
        "source_path": "" if count == 0 else f"fixture/{pool_id}.csv",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": rows,
        "cannot_confirm": ["EXPECTED_MISSING"] if count == 0 else [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_empty_root_materializes_seven_independent_pools_and_api_keeps_boundaries(tmp_path: Path) -> None:
    counts = [18, 0, 1, 14, 0, 100, 43]
    store = PreselectionPoolStore(tmp_path / "data")
    for pool_id, count in zip(POOL_ORDER, counts):
        store.materialize(_artifact(pool_id, count))

    body = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/preselection-pools", params={"date": "20260731", "limit": 200}
    ).json()

    assert body["ok"] is True
    assert [pool["pool_id"] for pool in body["pools"]] == list(POOL_ORDER)
    assert [pool["pool_size"] for pool in body["pools"]] == counts
    assert body["row_count"] == 176
    assert body["pool_count"] == 7
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False
    assert len(list((store.root / "preselection_pools/20260731/receipts").glob("*.json"))) == 7


def test_incomplete_independent_pool_set_keeps_each_lane_explicit(tmp_path: Path) -> None:
    store = PreselectionPoolStore(tmp_path / "data")
    store.materialize(_artifact("a_d1_premarket_pool", 1))
    body = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/preselection-pools", params={"date": "20260731"}
    ).json()
    assert body["ok"] is True
    assert body["data_status"] == "PARTIAL_WITH_ROWS"
    assert body["trade_date"] == "20260731"
    assert [pool["pool_id"] for pool in body["pools"]] == list(POOL_ORDER)
    assert body["pools"][0]["pool_size"] == 1
    missing = body["pools"][1:]
    assert len(missing) == 6
    assert all(pool["status"] == "CANNOT_CONFIRM" for pool in missing)
    assert {row["symbol"] for row in body["a_all_pool_rows"]} == {"A.000001"}
    assert all(row.get("market") != "HK" for row in body["a_all_pool_rows"])
    assert body["market_totals"] == {"A": 1, "HK": 0}
    assert all(
        pool[field] is False
        for pool in body["pools"]
        for field in ("production_allowed", "buy_gate_updated", "orders_sent")
    )
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_store_rejects_legacy_final_api_and_legacy_partial_identity(tmp_path: Path) -> None:
    store = PreselectionPoolStore(tmp_path / "data")
    final_api = _artifact("a_d1_premarket_pool", 1)
    final_api["source_role"] = "LEGACY_FINAL_API"
    with pytest.raises(ValueError, match="oracle-only"):
        store.materialize(final_api)

    legacy = _artifact("a_d1_premarket_pool", 1)
    legacy["pool_id"] = "legacy_partial_migration"
    with pytest.raises(ValueError, match="legacy"):
        store.materialize(legacy)


def test_existing_flat_import_is_not_projected_into_graph_pools(tmp_path: Path) -> None:
    row = {"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"}
    payload = {
        "schema_version": "v3_preselection_pools.v1", "trade_date": "20260731",
        "producer_status": "PARTIAL", "data_status": "PARTIAL_WITH_ROWS",
        "module_id": "unified_preselection_pools", "write_policy": "read_only",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "canonical_main_pool_confirmed": False, "source_lane": "NON_CANONICAL_OBSERVATION",
        "selector_status": "CANNOT_CONFIRM", "strict_0_2_status": "CANNOT_CONFIRM",
        "pools": [{"pool_id": "legacy_partial_migration", "rows": [row]}],
        "rows": [row], "unified_rows": [row], "a_source_only_rows": [],
        "a_all_pool_rows": [row], "startup_ensure": {}, "evidence_paths": [], "cannot_confirm": [],
    }
    NativeDataStore(tmp_path / "data").import_payload(payload)
    body = TestClient(create_app(data_root=tmp_path / "data")).get(
        "/api/v3/preselection-pools", params={"date": "20260731"}
    ).json()
    assert body["ok"] is False
    assert body["pool_count"] == 0
    assert body["blocking_reasons"] == [
        "V3.5 independent preselection producers have not materialized this date."
    ]


def test_wechat_and_missing_baimao_keep_exact_date_research_boundaries(tmp_path: Path) -> None:
    rows_path = tmp_path / "wechat.csv"
    rows_path.write_text("ts_code,name\n000001.SZ,平安银行\n", encoding="utf-8-sig")
    manifest_path = tmp_path / "wechat.manifest.json"
    manifest_path.write_text(json.dumps({
        "status": "WECHAT_V3_PRESELECT_READY",
        "signal_date": "20260730",
        "article_publish_date": "20260730",
        "target_date": "20260730",
        "effective_trade_date": "20260731",
        "target_validation": {
            "status": "TARGET_DATE_CHECK_PASS",
            "date_match": True,
            "title_match": True,
            "allow_mismatch": False,
        },
        "score_scope": "wechat_pool_ts_codes_only",
        "boundary": {"formal_pool_write": False, "buy_gate_write": False},
        "counts": {"v3_matched_codes": 1},
    }, ensure_ascii=False), encoding="utf-8")

    wechat = build_wechat_pool(manifest_path, rows_path, "20260731")
    assert [row["symbol"] for row in wechat["rows"]] == ["A.000001"]
    assert wechat["source_role"] == "VERIFIED_WECHAT_RESEARCH"
    assert wechat["cannot_confirm"] == ["RESEARCH_ONLY_NO_BUY_GATE"]
    with pytest.raises(ValueError, match="date mismatch"):
        build_wechat_pool(manifest_path, rows_path, "20260803")

    baimao = build_baimao_pool(None, "20260731")
    assert baimao["rows"] == []
    assert baimao["status"] == "CANNOT_CONFIRM"
    assert baimao["source_role"] == "EXPECTED_MISSING"
