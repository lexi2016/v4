"""V4 r10 closing regression tests: all 10 deployed frontend validators & all 6/6 scheduling slots execution_ref."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import re
from threading import Event

import pytest

from fastapi.testclient import TestClient

from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.runner import cli
from v4_core.runner.slots import (
    SIX_SLOT_DEFS,
    run_slot,
    run_slot_1_preopen_research,
    run_slot_2_preopen_pool_freeze,
    run_slot_3_intraday_stage,
    run_slot_4_a_share_daily,
    run_slot_5_hk_and_evening,
    run_slot_6_review_and_maint,
)
from v4_core.storage.db import V4Store

UPPER_STATUS_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")
HEX32_RE = re.compile(r"^[a-f0-9]{32}$")
YYYYMMDD_RE = re.compile(r"^\d{8}$")


def _cfg(tmp_path: Path) -> V4Config:
    cfg = V4Config(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data/v4.sqlite3",
        bars_dir=tmp_path / "data/bars",
        logs_dir=tmp_path / "logs",
        min_free_gib=0.01,
    )
    cfg.ensure_dirs()
    return cfg


def test_all_10_deployed_frontend_validator_contracts_pass(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)

    # Seed same-day authority name for SZ.301252 -> 同星科技 + preselection & stage rows
    store.upsert_security_master([
        {"trade_date": "2026-11-24", "market": "A", "symbol": "301252.SZ", "display_name": "同星科技", "industry": "热管理"},
    ])
    store.upsert_preselection_pools([
        {"trade_date": "20261124", "pool_name": "a_share_d1", "market": "A", "symbol": "SZ.301252", "status": "READY"},
    ])
    store.upsert_stage_selections([
        {
            "trade_date": "20261124",
            "stage": "STAGE_0930_0935",
            "market": "A",
            "symbol": "SZ.301252",
            "rank": 1,
            "execution_ref": "v4core://2026-11-24/slot_3_intraday_stage/test1",
        }
    ])
    store.upsert_research_materials([
        {
            "record_id": "r9-doc",
            "source_type": "pdf",
            "trade_date": "2026-11-24",
            "symbol": "301252.SZ",
            "title": "同星科技研报",
            "payload": {"pages": [{"page_number": 1, "text": "summary"}]},
        }
    ])

    client = TestClient(create_app(cfg))

    # 1. pool (pool_stage.ts:validatePoolResponse)
    pool = client.get("/api/v4/preselection-pools", params={"date": "20261124", "limit": 200, "offset": 0}).json()
    assert pool["trade_date"] == "20261124"
    assert pool["requested_date"] == "20261124"
    assert pool["selected_date"] == "20261124"
    assert UPPER_STATUS_RE.match(pool["data_status"])
    assert pool["write_policy"] == "read_only"
    assert pool["RESEARCH_ONLY"] is True
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent", "write_performed"):
        assert pool[flag] is False
    assert isinstance(pool["pools"], list) and pool["pool_count"] == len(pool["pools"])
    for grp in pool["pools"]:
        assert isinstance(grp["pool_id"], str) and grp["pool_id"]
        assert grp["market"] in {"A", "HK"}
        assert grp["page_offset"] == 0 and grp["page_limit"] == 200
        assert grp["returned_rows"] == len(grp["rows"])
    assert pool["pagination"]["offset"] == 0 and pool["pagination"]["limit"] == 200
    assert isinstance(pool["pagination"]["has_more"], bool)
    assert "next_offset" in pool["pagination"]

    # 2. stage (pool_stage.ts:validateStageResponse) & manager_stage
    for url in ("/api/v4/workbench/stage", "/api/v4/manager/stage-selection"):
        st = client.get(url, params={"date": "20261124", "stage": "STAGE_0930_0935", "limit": 50}).json()
        assert st["trade_date"] == "20261124"
        assert st["stage_id"] == "STAGE_0930_0935"
        assert UPPER_STATUS_RE.match(st["status"])
        assert st["RESEARCH_ONLY"] is True and st["write_performed"] is False
        assert st["production_allowed"] is False and st["buy_gate_updated"] is False and st["orders_sent"] is False
        assert isinstance(st["stage"], dict) and isinstance(st["stage"]["display_status"], str)
        assert set(st["markets"].keys()) == {"A", "HK"}
        assert st["markets"]["HK"]["market"] == "HK_CONNECT"
        assert set(st["selection_markets"].keys()) == {"A_SHARE", "HK_CONNECT"}
        assert isinstance(st["selected_a_rows"], int) and st["selected_a_rows"] == 1
        assert isinstance(st["unified_rows"], list) and len(st["unified_rows"]) == 1
        row0 = st["unified_rows"][0]
        assert row0["trade_date"] == "20261124" and row0["stage_id"] == "STAGE_0930_0935"
        assert row0["name"] == "同星科技" and row0["stock_name"] == "同星科技"

    # 3 & 4. manual_start & manual_job (manualCollection.ts)
    mc_start = client.post("/api/v4/manual-collection", json={"date": "20261124", "target": "HK_STAGE"}).json()
    assert HEX32_RE.match(mc_start["job_id"])
    assert isinstance(mc_start["trade_date"], str) and mc_start["trade_date"] == "20261124"
    mc_get = client.get(f"/api/v4/manual-collection/{mc_start['job_id']}").json()
    assert HEX32_RE.match(mc_get["job_id"]) and isinstance(mc_get["trade_date"], str)
    mc_missing = client.get("/api/v4/manual-collection/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").json()
    assert HEX32_RE.match(mc_missing["job_id"]) and isinstance(mc_missing["trade_date"], str)

    # 5. machine-cards (research_lane.ts:fetchMachineCards)
    cards = client.get("/api/v4/research/machine-cards", params={"research_date": "20261124"}).json()
    assert cards["schema_version"] == "v4.pdf_research.machine_cards.v1"
    assert cards["endpoint_mode"] == "EXACT" and cards["research_date"] == "20261124"
    assert cards["status"] in {"READY", "NOT_MATERIALIZED"}
    assert isinstance(cards["cards"], list) and isinstance(cards["items"], list)
    assert isinstance(cards["card_count"], int) and not isinstance(cards["card_count"], bool) and cards["card_count"] >= 0
    assert cards["card_count"] == len(cards["cards"]) == cards["count"] == cards["matched_count"]
    assert isinstance(cards["max_cards_per_date"], int) and cards["max_cards_per_date"] > 0
    assert isinstance(cards["preview_max_chars"], int) and not isinstance(cards["preview_max_chars"], bool) and cards["preview_max_chars"] >= 0
    assert isinstance(cards["duplicate_count"], int) and cards["duplicate_count"] >= 0
    assert isinstance(cards["cannot_confirm"], list)
    assert isinstance(cards["cannot_confirm_count"], int) and cards["cannot_confirm_count"] >= 0
    assert isinstance(cards["cannot_confirm_document_ids"], list)
    assert isinstance(cards["unresolved_document_ids"], list)
    assert isinstance(cards["source_index_used"], bool)
    assert isinstance(cards["truncated"], bool)
    assert cards["write_policy"] == "read_only" and cards["recommendation_status"] == "RESEARCH_ONLY"
    assert cards["research_only"] is True and cards["RESEARCH_ONLY"] is True
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert cards[flag] is False

    # 6. stock-clues (research_lane.ts:fetchStockClues)
    clues = client.get("/api/v4/research/stock-clues", params={"research_date": "20261124", "limit": 50}).json()
    assert clues["schema_version"] == "v4.research.stock_clues.v1"
    assert clues["endpoint_mode"] == "EXACT" and clues["research_date"] == "20261124"
    assert clues["status"] in {"READY", "NOT_MATERIALIZED"}
    assert isinstance(clues["clues"], list) and isinstance(clues["items"], list)
    for int_key in (
        "card_count",
        "scanned_card_count",
        "skipped_card_count",
        "stock_count",
        "confirmed_stock_count",
        "weak_only_stock_count",
        "corpus_report_count",
        "truncated_report_count",
        "clue_limit",
        "cannot_confirm_count",
    ):
        assert isinstance(clues[int_key], int) and not isinstance(clues[int_key], bool) and clues[int_key] >= 0
    assert clues["card_count"] == len(clues["clues"]) == clues["count"] == clues["clue_count"] == clues["matched_count"]
    assert clues["clue_limit"] == clues["limit"] == 50
    assert clues["status"] == "NOT_MATERIALIZED"
    assert clues["name_map_status"] == clues["corpus_cache_status"] == "CANNOT_CONFIRM"
    assert clues["name_map_path"] == clues["name_map_trade_date"] == clues["corpus_fingerprint"] == ""
    assert clues["corpus_cutoff_date"] == "20261124" and clues["corpus_version"]
    assert clues["generic_filtered"] == clues["weak_items"] == clues["items"] == []
    assert isinstance(clues["truncated"], bool)
    assert isinstance(clues["cannot_confirm"], list)
    assert clues["write_policy"] == "read_only" and clues["recommendation_status"] == "RESEARCH_ONLY"
    assert clues["research_only"] is True and clues["RESEARCH_ONLY"] is True
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert clues[flag] is False

    # 7 & 8. lane_exact & lane_latest (research_lane.ts:validateResearchLaneResponse)
    lane_exact = client.get("/api/v4/research/lane", params={"research_date": "20261124"}).json()
    assert lane_exact["schema_version"] == "v3_5.research_lane.v1"
    assert lane_exact["endpoint_mode"] == "EXACT" and lane_exact["research_date"] == "20261124"
    assert lane_exact["write_policy"] == "read_only" and lane_exact["recommendation_status"] == "RESEARCH_ONLY"
    lane_latest = client.get("/api/v4/research/lane").json()
    assert lane_latest["schema_version"] == "v3_5.research_lane.v1" and lane_latest["endpoint_mode"] == "LATEST"

    # 9. research_day (research_lane.ts:validateResearchDayResponse)
    rday = client.get("/api/v4/research/day", params={"archive_date": "20261124"}).json()
    assert rday["schema_version"] == "v3_5.research_day_product.v1"
    assert rday["status"] in {"READY", "READY_WITH_DECLARED_GAPS", "NOT_MATERIALIZED"}
    assert rday["endpoint_mode"] == "EXACT"
    assert isinstance(rday["authoritative"], bool)
    assert YYYYMMDD_RE.match(rday["archive_date"]) and rday["archive_date"] == "20261124"
    assert rday["write_policy"] == "read_only" and rday["recommendation_status"] == "RESEARCH_ONLY"
    for f in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert rday[f] is False
    if rday["status"] != "NOT_MATERIALIZED":
        assert rday["is_full_day"] is True
        for k in ("raw_rows", "evidence_rows", "excluded_rows", "mention_pairs", "urls", "stock_rollups", "high_priority", "duplicate_pairs"):
            assert isinstance(rday["counts"][k], int) and rday["counts"][k] >= 0
        assert isinstance(rday["coverage"]["complete"], bool)
        assert isinstance(rday["coverage"]["expected_slots"], int)
        assert isinstance(rday["coverage"]["ready_slots"], int)
        assert isinstance(rday["coverage"]["missing_slots"], list)
        assert isinstance(rday["coverage"]["slot_matrix"], list)

    # 10. pdf (research_lane.ts:loadResearchPdfDocumentDetail)
    pdf = client.get("/api/v4/research/pdf-documents/r9-doc", params={"research_date": "undefined"}).json()
    assert pdf["schema_version"] == "v4.zsxq_pdf_document_detail.v1"
    assert pdf["document_id"] == "r9-doc"
    assert pdf["research_date"] == "undefined"
    assert isinstance(pdf["pages"], list) and all(isinstance(pg, dict) for pg in pdf["pages"])

    # task_status minimum fields (timeline_nodes + runtime.ts contract)
    ts = client.get("/api/v4/tasks/status", params={"date": "20261124"}).json()
    assert isinstance(ts["timeline_nodes"], list) and len(ts["timeline_nodes"]) == 6
    assert isinstance(ts["groups"], dict) and "logical" in ts["groups"]
    assert ts["production_allowed"] is False and ts["buy_gate_updated"] is False and ts["orders_sent"] is False


def test_research_machine_cards_projects_only_bound_items(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    day = "20261124"
    payload = {
        "document_id": "official-doc",
        "research_date": "2026-11-24",
        "status": "READY",
        "title": "昨日收盘研究",
        "batch_id": "owner-batch",
        "superseded_batch_ids": ["previous-batch"],
        "source": {"original_filename": "archive.pdf", "source_group_name": None, "source_directory": "official"},
        "review": {"human_reviewed": False, "review_status": "NOT_REVIEWED"},
        "report": {"preview": "文" * 241, "path": "archive.md"},
        "machine_generated": True,
        "read_only": True,
    }
    store.upsert_research_materials([
        {"record_id": "store-row", "source_type": "machine_card", "trade_date": day, "payload": payload},
        {"record_id": "previous-date", "source_type": "machine_card", "trade_date": "20261123",
         "applicable_date": day, "payload": {**payload, "document_id": "previous-doc", "research_date": "20261123"}},
        {"record_id": "unsafe-row", "source_type": "machine_card", "trade_date": day,
         "payload": {**payload, "document_id": "unsafe-doc", "production_allowed": True}},
    ])
    with TestClient(create_app(cfg)) as client:
        res = client.get("/api/v4/research/machine-cards", params={"research_date": day})
        assert res.status_code == 200
        cards = res.json()
        assert cards["status"] == "READY" and cards["card_count"] == 1
        assert cards["matched_count"] == 3 and cards["cannot_confirm_count"] == 2
        assert set(cards["unresolved_document_ids"]) == {"previous-doc", "unsafe-doc"}
        assert cards["cards"] == cards["items"]
        card, = cards["items"]
        assert card["document_id"] == "official-doc" and card["research_date"] == day
        assert card["status"] == "READY" and card["title"] == payload["title"]
        assert card["superseded_batch_ids"] == ["previous-batch"] and card["batch_id"] == "owner-batch"
        assert all(card["source"][k] == v for k, v in payload["source"].items())
        assert card["source"]["source_group_status"] == "CANNOT_CONFIRM"
        assert card["source"]["source_pdf_path"] == card["source"]["source_relative_path"] == ""
        assert all(card["review"][k] == v for k, v in payload["review"].items())
        assert card["review"]["user_acceptance_status"] is None and card["review"]["user_accepted"] is False
        assert card["report"] == {"preview": "文" * 240, "path": "archive.md", "preview_max_chars": 240,
                                  "receipt_path": "", "sha256": None, "bytes": None}
        assert all(card[flag] is True for flag in ("machine_generated", "read_only", "research_only"))
        assert all(card[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        assert "payload" not in card
        empty = client.get("/api/v4/research/machine-cards", params={"research_date": "20261125"}).json()
        assert empty["status"] == "NOT_MATERIALIZED" and empty["items"] == [] and empty["card_count"] == 0


def test_stock_clues_withhold_actionable_rows_when_scan_unverified(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    day = "20261124"
    payload = {
        "ts_code": "301252.SZ", "name": "同星科技", "research_date": day, "document_count": 2,
        "weak_document_count": 1, "link_probability": 0.8, "confirm_reasons": ["CODE", "CONTEXT"],
        "document_titles": [str(i) for i in range(6)], "matched_by": "BOTH",
        "first_seen_date": "2026-11-21", "last_seen_date": day,
    }
    store.upsert_research_materials([
        {"record_id": "a", "source_type": "stock_clue", "trade_date": day, "symbol": "301252.SZ", "payload": payload},
        {"record_id": "b", "source_type": "stock_clue", "trade_date": "2026-11-24",
         "payload": {**payload, "ts_code": "000026.SZ", "name": None}},
        {"record_id": "bare-name-hit", "source_type": "stock_clue", "trade_date": day,
         "payload": {"ts_code": "603529.SH", "name": "爱玛科技"}},
        {"record_id": "future-date", "source_type": "stock_clue", "trade_date": day,
         "payload": {**payload, "ts_code": "600519.SH", "last_seen_date": "20261125"}},
        *[
            {"record_id": code, "source_type": "stock_clue", "trade_date": day,
             "payload": {"ts_code": code, "name": code, "document_count": 0, "weak_document_count": weak}}
            for code, weak in (("920770.BJ", 1), ("000002.SZ", 3), ("000001.SZ", 3), ("301252.SZ", 4))
        ],
    ])
    with TestClient(create_app(cfg)) as client:
        query = {"research_date": day, "limit": 1}
        res = client.get("/api/v4/research/stock-clues", params=query)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "CANNOT_CONFIRM"
        assert body["stock_count"] == body["confirmed_stock_count"] == body["weak_only_stock_count"] == 0
        assert body["items"] == body["clues"] == body["weak_items"] == []
        assert body["clue_limit"] == 1 and body["truncated"] is False
        assert body["source_observations"] == {
            "rows_read": 8, "unverified_rows": 2,
            "codes_with_confirmed_payload": 2, "codes_with_weak_only_payload": 3,
        }
        assert body["name_map_status"] == body["corpus_cache_status"] == "CANNOT_CONFIRM"
        assert body["name_map_path"] == body["name_map_trade_date"] == body["corpus_fingerprint"] == ""
        assert body["corpus_report_count"] == body["card_count"] == body["scanned_card_count"] == 0
        assert body["corpus_cutoff_date"] == day and body["generic_filtered"] == []
        assert body["cannot_confirm_count"] == len(body["cannot_confirm"])
        assert set(body["cannot_confirm"]) == {
            "STOCK_CLUE_NAME_MAP_UNAVAILABLE", "STOCK_CLUE_CORPUS_UNAVAILABLE",
            "STOCK_CLUE_SCAN_PROVENANCE_UNAVAILABLE", "STOCK_CLUE_PAYLOAD_UNVERIFIED",
        }
        whole = client.get("/api/v4/research/stock-clues", params={"research_date": day}).json()
        assert whole["status"] == "CANNOT_CONFIRM" and whole["items"] == []
        assert whole["source_observations"] == body["source_observations"]
        assert len(store.query_research_materials(source_type="stock_clue", limit=100)) == 8
        for invalid_limit in (0, 201):
            assert client.get("/api/v4/research/stock-clues",
                              params={**query, "limit": invalid_limit}).status_code == 422


def test_stock_clues_weak_only_does_not_claim_a_completed_scan(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    day = "20261124"
    store.upsert_research_materials([{
        "record_id": "weak", "source_type": "stock_clue", "trade_date": day,
        "payload": {"ts_code": "000026.SZ", "name": "飞亚达", "document_count": 0, "weak_document_count": 1},
    }])
    with TestClient(create_app(cfg)) as client:
        body = client.get("/api/v4/research/stock-clues", params={"research_date": day}).json()
        assert body["status"] == "CANNOT_CONFIRM" and body["weak_items"] == []
        assert body["weak_only_stock_count"] == 0
        assert body["source_observations"]["codes_with_weak_only_payload"] == 1
        empty = client.get("/api/v4/research/stock-clues", params={"research_date": "20261123"}).json()
        assert empty["status"] == "NOT_MATERIALIZED" and empty["source_observations"]["rows_read"] == 0


def test_research_applicable_date_cannot_backdate_later_evidence(tmp_path: Path):
    cfg = _cfg(tmp_path)
    day = "20261124"
    stock = {
        "ts_code": "301252.SZ", "name": "同星科技", "document_count": 1, "weak_document_count": 0,
        "confirm_reasons": ["CODE"], "document_titles": ["归档报告"], "matched_by": "CODE",
        "first_seen_date": day, "last_seen_date": day,
    }
    V4Store(cfg.db_path).upsert_research_materials([
        {"record_id": "late-card", "source_type": "machine_card", "trade_date": "2026-11-26",
         "applicable_date": day, "payload": {
             "document_id": "future-doc", "research_date": day, "status": "READY", "title": "归档报告",
             "superseded_batch_ids": [], "source": {"original_filename": "future.pdf"},
             "review": {"human_reviewed": False}, "report": {"preview": "证据"},
             "machine_generated": True, "read_only": True,
         }},
        {"record_id": "late-legacy-clue", "source_type": "stock_clue", "trade_date": "20261126",
         "applicable_date": day, "payload": stock},
        {"record_id": "late-explicit-clue", "source_type": "stock_clue", "trade_date": "20261126",
         "applicable_date": day, "payload": {**stock, "research_date": day}},
        {"record_id": "previous-legacy-clue", "source_type": "stock_clue", "trade_date": "20261123",
         "applicable_date": day, "payload": stock},
    ])
    with TestClient(create_app(cfg)) as client:
        query = {"research_date": day}
        cards = client.get("/api/v4/research/machine-cards", params=query).json()
        assert cards["status"] == "NOT_MATERIALIZED"
        assert cards["matched_count"] == cards["card_count"] == cards["cannot_confirm_count"] == 0
        assert cards["items"] == cards["unresolved_document_ids"] == []
        clues = client.get("/api/v4/research/stock-clues", params=query).json()
        assert clues["status"] == "CANNOT_CONFIRM" and "STOCK_CLUE_PAYLOAD_UNVERIFIED" in clues["cannot_confirm"]
        assert clues["stock_count"] == clues["confirmed_stock_count"] == clues["weak_only_stock_count"] == 0
        assert clues["items"] == clues["weak_items"] == []


def test_five_manual_slots_write_and_readback_execution_ref(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    trade_date = "2026-11-24"

    # Clean date must report execution_ref=None before any slot executes (no fake pending refs)
    client = TestClient(create_app(cfg))
    clean_wf = client.get("/api/v4/research/workbench/workflow-contract", params={"source_date": "2026-11-23"}).json()
    assert all(row["execution_ref"] is None for row in clean_wf["rows"])
    clean_ts = client.get("/api/v4/tasks/status", params={"date": "2026-11-23"}).json()
    assert all(node["execution_ref"] is None for node in clean_ts["timeline_nodes"])

    # Prepare minimal bars, adj_factors & selections so Slot 4 completes end-to-end
    store.upsert_daily_bars([
        {"market": "A", "symbol": "000026.SZ", "trade_date": trade_date, "open": 22.0, "high": 22.5, "low": 21.8, "close": 22.35, "volume": 1000, "amount": 22350, "pre_close": 22.0},
    ])
    store.upsert_adj_factors([
        {"market": "A", "symbol": "000026.SZ", "trade_date": trade_date, "adj_factor": 1.0},
    ])
    store.upsert_workbench_selections([
        {"trade_date": trade_date, "symbol": "000026.SZ", "selection_group": "192", "display_name": "飞亚达"},
    ])

    # The manual Review Core path leaves the authoritative slot untouched.
    r1 = run_slot_1_preopen_research(cfg, trade_date)
    r2 = run_slot_2_preopen_pool_freeze(cfg, trade_date)
    r3 = run_slot_3_intraday_stage(cfg, trade_date)
    r4 = run_slot_4_a_share_daily(cfg, trade_date, sse_notifier=lambda dt, s: True)
    r5 = run_slot_5_hk_and_evening(cfg, trade_date)
    r6 = run_slot_6_review_and_maint(cfg, trade_date)

    for sid, res in zip(SIX_SLOT_DEFS.keys(), (r1, r2, r3, r4, r5)):
        assert res["execution_ref"].startswith(f"v4core://{trade_date}/{sid}/")
    assert r6["status"] == "CANNOT_CONFIRM" and r6["execution_ref"] is None
    assert store.get_review_record(trade_date) is None

    # Verify dispatcher run_slot works too
    r1_again = run_slot(cfg, trade_date, "slot_1_preopen_research")
    assert r1_again["execution_ref"].startswith(f"v4core://{trade_date}/slot_1_preopen_research/")

    # The six-slot display retains the five bound receipts for ISO and compact dates.
    for dt_param in ("2026-11-24", "20261124"):
        wf = client.get("/api/v4/research/workbench/workflow-contract", params={"source_date": dt_param}).json()
        assert wf["slot_count"] == 6
        assert sum(row["status"] == "DONE" and bool(row["execution_ref"]) for row in wf["rows"]) == 5
        assert wf["rows"][-1]["execution_ref"] is None

        ts = client.get("/api/v4/tasks/status", params={"date": dt_param}).json()
        assert ts["scheduler_observation"]["executed_slots"] == 5
        assert sum(node["status"] == "DONE" and bool(node["execution_ref"]) for node in ts["timeline_nodes"]) == 5
        assert ts["timeline_nodes"][-1]["execution_ref"] is None


def test_daily_plist_exact_r16_calendar_and_source_gaps(tmp_path: Path):
    cfg = _cfg(tmp_path / "data_home")
    day = "2026-11-24"
    expected = {
        "09:25": "main_preopen", "09:35": "main_stage", "09:40": "main_stage", "09:45": "main_stage",
        "10:30": "main_stage", "13:15": "main_stage", "15:00": "main_stage7", "15:40": "source_check",
        "15:55": "main_stage", "16:10": "a_daily", "17:20": "hk_ingest", "17:30": "hk_cache_write",
        "18:00": "hk_cache_read", "19:00": "evening", "21:15": "review",
    }
    factors = tmp_path / "adjustments.json"
    selections = tmp_path / "selections.json"
    hk = tmp_path / "hk_bars.json"
    evidence = tmp_path / "inputs"
    times = [tuple(map(int, value.split(":"))) for value in expected]
    plist = plistlib.loads(cli.generate_daily_scheduler_plist(
        tmp_path, "/verified/python", tdx_dir=tmp_path / "tdx",
        factors_json=factors, selections_json=selections, hk_bars_json=hk, evidence_dir=evidence,
    ))
    assert plist["ProgramArguments"] == ["/verified/python", "-m", "v4_core", "run-slot", "--scheduled"]
    assert plist["StartCalendarInterval"] == [{"Hour": h, "Minute": m} for h, m in times]
    assert plist["Label"] == "com.lexi.v4core.daily" and "KeepAlive" not in plist and "RunAtLoad" not in plist
    assert plist["EnvironmentVariables"] == {
        "PYTHONPATH": str(tmp_path.resolve()), "V4_CORE_HOME": str(tmp_path.resolve() / "v4_data"),
        "TZ": "Asia/Shanghai", "V4_TDX_DIR": str(tmp_path.resolve() / "tdx"),
        "V4_FACTORS_JSON": str(factors.resolve()), "V4_SELECTIONS_JSON": str(selections.resolve()),
        "V4_HK_BARS_JSON": str(hk.resolve()), "V4_R16_INPUT_DIR": str(evidence.resolve()),
    }
    with pytest.raises(ValueError, match="distinct configured windows"):
        cli.generate_daily_scheduler_plist(tmp_path, "/verified/python", schedules=[(9, 25), (9, 25)])

    hk.write_text(json.dumps([
        {"symbol": "00005.HK", "trade_date": "20261123", "open": 50, "high": 51, "low": 49,
         "close": 50, "amount": 50000, "volume": 1000},
        {"symbol": "00005.HK", "trade_date": "20261124", "open": 50, "high": 51, "low": 49,
         "close": 50, "amount": 50000, "volume": 1000},
    ]))
    for (h, m), (window, phase) in zip(times, expected.items(), strict=True):
        at = datetime(2026, 11, 24, h, m, 13, tzinfo=cli.BEIJING)
        result = cli.run_scheduled_window(cfg, at.astimezone(timezone.utc), hk_bars_json=hk)
        assert (result["window"], result["phase"]) == (window, phase)
        assert cli.run_scheduled_window(cfg, at)["schedule_status"] == "ALREADY_ATTEMPTED"
        receipts = (cfg.logs_dir / "daily_windows" / f"{day}_{h:02d}{m:02d}.jsonl").read_text().splitlines()
        assert [json.loads(line)["schedule_status"] for line in receipts] == ["RUNNING", result["schedule_status"]]
        if phase == "hk_ingest":
            assert result["workload"]["detail"]["hk_ingested_accepted"] == 1
            assert result["workload"]["detail"]["hk_ingested_quarantined"] == 0
        else:
            assert result["schedule_status"] == "CANNOT_CONFIRM"
    assert V4Store(cfg.db_path).get_review_record(day) is None
    assert cli.run_scheduled_window(cfg, datetime(2026, 11, 24, 9, 43, tzinfo=cli.BEIJING))["schedule_status"] == "NO_DUE_WORKLOADS"


def test_natural_daily_window_concurrent_duplicate_and_failed_receipt(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    at = datetime(2026, 11, 24, 9, 25, tzinfo=cli.BEIJING)
    started, release = Event(), Event()

    def failing_workload(*args, **kwargs):
        started.set()
        assert release.wait(5)
        raise RuntimeError("isolated source failure")

    monkeypatch.setattr(cli, "run_slot", failing_workload)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(cli.run_scheduled_window, cfg, at)
        try:
            assert started.wait(5)
            assert cli.run_scheduled_window(cfg, at)["schedule_status"] == "ALREADY_RUNNING"
            cross_window = at.replace(minute=35)
            assert cli.run_scheduled_window(cfg, cross_window)["schedule_status"] == "WRITER_BUSY"
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="isolated source failure"):
            first.result()
    assert cli.run_scheduled_window(cfg, at)["schedule_status"] == "ALREADY_ATTEMPTED"
    rows = (cfg.logs_dir / "daily_windows" / "2026-11-24_0925.jsonl").read_text().splitlines()
    assert [json.loads(row)["schedule_status"] for row in rows] == ["RUNNING", "FAILED"]


def test_daily_late_dispatch_keeps_scheduled_identity_and_reports_missed_windows(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []

    def record_slot(_cfg, day, slot, *, phase, **options):
        calls.append((day, slot, phase))
        return {"status": "CANNOT_CONFIRM"}

    monkeypatch.setattr(cli, "run_slot", record_slot)
    at = datetime(2026, 11, 24, 9, 36, 15, tzinfo=cli.BEIJING)
    result = cli.run_scheduled_window(cfg, at)
    assert result["scheduled_for"] == "2026-11-24T09:35:00+08:00"
    assert result["observed_at"] == at.isoformat() and result["window"] == "09:35"
    assert result["timing_status"] == "LATE_DISPATCH" and result["delay_seconds"] == 75
    assert result["unobserved_earlier_windows"] == ["09:25"]
    assert cli.run_scheduled_window(cfg, at)["schedule_status"] == "ALREADY_ATTEMPTED"

    # The previous calendar job that might coalesce on wake has no valid due binding.
    no_due = cli.run_scheduled_window(cfg, datetime(2026, 11, 24, 9, 43, tzinfo=cli.BEIJING))
    assert no_due["schedule_status"] == "NO_DUE_WORKLOADS"
    assert no_due["reason"] == "OUTSIDE_CONFIGURED_WINDOW_GRACE"
    assert no_due["unobserved_earlier_windows"] == ["09:25", "09:40"]
    assert calls == [("2026-11-24", "slot_3_intraday_stage", "main_stage")]
    assert [p.name for p in (cfg.logs_dir / "daily_windows").iterdir()] == ["2026-11-24_0935.jsonl"]
