from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.stage_input_producer import StageInputProducer
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_overlay_store import PreselectionOverlayStore
from infrastructure.stage_store import StageStore
from ops.import_preselection_overlays import (
    _contract,
    build_optional_pool_overlay,
    main as import_overlays,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "migration" / "preselection_optional_pools_v1.json"
OPTIONAL_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "preselection_optional_pools"
OPTIONAL_FIXTURE_MANIFEST = OPTIONAL_FIXTURE_ROOT / "manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_payload(date: str) -> dict:
    rows = [
        {"symbol": "A.000001", "market": "A", "pool_id": "a_d1_premarket_pool", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "A.000002", "market": "A", "pool_id": "a_d1_fupan_watchlist_pool", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "A.000003", "market": "A", "pool_id": "a_d1_stage7_fenshi_review_pool", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "A.000004", "market": "A", "pool_id": "a_share_research_recommendation_pool", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "HK.00001", "market": "HK", "pool_id": "hkconnect_d1_top100", "recommendation_status": "WATCH_ONLY"},
    ]
    return {
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": date,
        "producer_status": "PARTIAL",
        "data_status": "PARTIAL_WITH_ROWS",
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "canonical_main_pool_confirmed": False,
        "source_lane": "NON_CANONICAL_OBSERVATION",
        "selector_status": "CANNOT_CONFIRM",
        "strict_0_2_status": "CANNOT_CONFIRM",
        "pools": [{"pool_id": "legacy_partial_migration", "rows": deepcopy(rows)}],
        "unified_rows": deepcopy(rows),
        "a_source_only_rows": deepcopy(rows[:4]),
        "a_all_pool_rows": deepcopy(rows[:4]),
        "rows": deepcopy(rows),
        "startup_ensure": {},
        "evidence_paths": [],
        "cannot_confirm": [],
    }


def _write_source_pair(tmp_path: Path, date: str = "20260730") -> tuple[Path, Path, dict]:
    csv_path = tmp_path / "wechat.csv"
    fields = [
        "ts_code", "code", "name", "display_name", "trade_date", "publish_date",
        "article_title", "wechat_hit_count", "wechat_theme", "wechat_source_ref",
        "candidate_score", "guard_pass", "v3_match", "formal_pool_write",
        "buy_gate_write", "wechat_pool_lane", "source_tags", "v3_preselect_status",
        "wechat_v3_preselect_rank",
    ]
    rows = [
        {
            "ts_code": "000001.SZ", "code": "000001", "name": "平安银行",
            "display_name": "平安银行（研）", "trade_date": date,
            "publish_date": "2026-07-30", "article_title": "冻结文章",
            "wechat_hit_count": "1", "wechat_theme": "微信观察",
            "wechat_source_ref": "https://example.invalid/a", "candidate_score": "5.5",
            "guard_pass": "True", "v3_match": "True", "formal_pool_write": "False",
            "buy_gate_write": "False", "wechat_pool_lane": "research_lane_observation_preselect",
            "source_tags": "（研）", "v3_preselect_status": "V3_GUARD_PASS_OBSERVATION_PRESELECT",
            "wechat_v3_preselect_rank": "1",
        },
        {
            "ts_code": "600000.SH", "code": "600000", "name": "浦发银行",
            "display_name": "浦发银行（研）", "trade_date": date,
            "publish_date": "2026-07-30", "article_title": "冻结文章",
            "wechat_hit_count": "2", "wechat_theme": "微信观察",
            "wechat_source_ref": "https://example.invalid/b", "candidate_score": "4.25",
            "guard_pass": "False", "v3_match": "True", "formal_pool_write": "False",
            "buy_gate_write": "False", "wechat_pool_lane": "research_lane_observation_preselect",
            "source_tags": "（研）", "v3_preselect_status": "V3_OBSERVATION_PRESELECT",
            "wechat_v3_preselect_rank": "2",
        },
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "status": "WECHAT_V3_PRESELECT_READY",
        "signal_date": date,
        "article_publish_date": date,
        "effective_trade_date": "20260731",
        "verify_date": "20260731",
        "selector_score_date": date,
        "target_date": date,
        "target_validation": {"status": "TARGET_DATE_CHECK_PASS", "date_match": True, "title_match": True, "allow_mismatch": False},
        "counts": {"wechat_unique_codes": 2, "v3_matched_codes": 2, "v3_unmatched_codes": 0},
        "outputs": {"all": str(csv_path)},
        "boundary": {"lane": "research_lane_observation_preselect", "formal_pool_write": False, "buy_gate_write": False},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, csv_path, manifest


def test_contract_freezes_graph_inputs_pool_boundaries_and_exact_counts() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["schema_version"] == "v3_5.preselection_optional_pools_contract.v1"
    body = {key: value for key, value in contract.items() if key != "semantic_hash"}
    assert contract["semantic_hash"] == hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert contract["graph_authority"]["graph_baseline_semantic_hash"] == "8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7"
    assert contract["expected_projection"]["pool_order"] == [
        "a_d1_premarket_pool",
        "a_d1_fupan_watchlist_pool",
        "a_d1_stage7_fenshi_review_pool",
        "a_share_research_recommendation_pool",
        "a_share_baimao_research_map",
        "hkconnect_d1_top100",
        "wechat_public_account_v3_preselect",
    ]
    assert list(contract["expected_projection"]["pool_sizes"].values()) == [19, 64, 70, 6, 0, 100, 43]
    assert contract["expected_projection"]["row_count"] == 302
    assert contract["expected_projection"]["unified_row_count"] == 19
    assert contract["expected_projection"]["a_all_pool_row_count"] == 186
    assert contract["boundaries"]["stage_input_reads_base_payload_only"] is True
    assert contract["boundaries"]["wechat_formal_pool_write"] is False
    assert all(
        len(item["raw_sha256"]) == 64
        for item in contract["frozen_inputs"].values()
        if "raw_sha256" in item
    )


def test_importer_rejects_alternate_same_schema_contract_before_writing(tmp_path: Path) -> None:
    alternate = tmp_path / "alternate-contract.json"
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    alternate.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    manifest_path, csv_path, _ = _write_source_pair(tmp_path)
    output_root = tmp_path / "data"

    with pytest.raises(ValueError, match="frozen authority path"):
        import_overlays([
            "--manifest", str(manifest_path),
            "--rows", str(csv_path),
            "--contract", str(alternate),
            "--data-root", str(output_root),
        ])

    assert not output_root.exists()
    assert _contract(CONTRACT_PATH)["semantic_hash"] == contract["semantic_hash"]


def test_importer_builds_strict_research_only_overlay_without_mutating_inputs(tmp_path: Path) -> None:
    manifest_path, csv_path, _ = _write_source_pair(tmp_path)
    before = {path: path.read_bytes() for path in (manifest_path, csv_path)}
    payload = build_optional_pool_overlay(
        manifest_path,
        csv_path,
        expected_manifest_sha256=_sha256(manifest_path),
        expected_rows_sha256=_sha256(csv_path),
        expected_business_date="20260730",
        expected_row_count=2,
    )
    assert {path: path.read_bytes() for path in before} == before
    assert [pool["pool_id"] for pool in payload["pools"]] == [
        "a_share_baimao_research_map",
        "wechat_public_account_v3_preselect",
    ]
    assert payload["pools"][0]["status"] == "CANNOT_CONFIRM"
    wechat = payload["pools"][1]
    assert [row["symbol"] for row in wechat["rows"]] == ["A.000001", "A.600000"]
    assert all(row["recommendation_status"] == "RESEARCH_ONLY" for row in wechat["rows"])
    assert all(row["trade_status_contract"] == "RESEARCH_ONLY_NO_BUY_GATE" for row in wechat["rows"])
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_importer_rejects_hash_date_rank_and_safety_drift(tmp_path: Path) -> None:
    manifest_path, csv_path, _ = _write_source_pair(tmp_path)
    common = {
        "expected_manifest_sha256": _sha256(manifest_path),
        "expected_rows_sha256": _sha256(csv_path),
        "expected_business_date": "20260730",
        "expected_row_count": 2,
    }
    with pytest.raises(ValueError, match="manifest SHA"):
        build_optional_pool_overlay(manifest_path, csv_path, **{**common, "expected_manifest_sha256": "0" * 64})

    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    rows[1]["wechat_v3_preselect_rank"] = "3"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="rank"):
        build_optional_pool_overlay(
            manifest_path, csv_path,
            expected_manifest_sha256=_sha256(manifest_path),
            expected_rows_sha256=_sha256(csv_path),
            expected_business_date="20260730", expected_row_count=2,
        )

    rows[1]["wechat_v3_preselect_rank"] = "2"
    rows[1]["buy_gate_write"] = "True"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="BUY gate"):
        build_optional_pool_overlay(
            manifest_path, csv_path,
            expected_manifest_sha256=_sha256(manifest_path),
            expected_rows_sha256=_sha256(csv_path),
            expected_business_date="20260730", expected_row_count=2,
        )


def test_overlay_store_is_exact_date_atomic_idempotent_and_fail_closed(tmp_path: Path) -> None:
    manifest_path, csv_path, _ = _write_source_pair(tmp_path)
    payload = build_optional_pool_overlay(
        manifest_path, csv_path,
        expected_manifest_sha256=_sha256(manifest_path),
        expected_rows_sha256=_sha256(csv_path),
        expected_business_date="20260730", expected_row_count=2,
    )
    store = PreselectionOverlayStore(tmp_path / "data")
    first = store.import_overlay(payload)
    assert store.import_overlay(payload) == first
    assert store.read_overlay("20260730") == payload
    assert store.read_overlay("20260729") is None
    conflict = deepcopy(payload)
    conflict["pools"][1]["rows"][0]["score"] = 999.0
    conflict["pools"][1]["rows"][0]["pool_score"] = 999.0
    with pytest.raises(ValueError, match="conflict"):
        store.import_overlay(conflict)
    receipt = store.root / first["receipt_path"]
    tampered = json.loads(receipt.read_text(encoding="utf-8"))
    tampered["payload_sha256"] = "0" * 64
    receipt.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA"):
        store.read_overlay("20260730")


def test_api_rejects_read_time_optional_pool_merge_without_changing_stage_input(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    base_store = NativeDataStore(data_root)
    base = _base_payload("20260730")
    base_store.import_payload(base)
    manifest_path, csv_path, _ = _write_source_pair(tmp_path)
    overlay = build_optional_pool_overlay(
        manifest_path, csv_path,
        expected_manifest_sha256=_sha256(manifest_path),
        expected_rows_sha256=_sha256(csv_path),
        expected_business_date="20260730", expected_row_count=2,
    )
    PreselectionOverlayStore(data_root).import_overlay(overlay)

    body = TestClient(create_app(data_root=data_root)).get(
        "/api/v3/preselection-pools", params={"date": "20260730", "limit": 200}
    ).json()

    assert body["ok"] is False
    assert body["pools"] == []
    assert body["blocking_reasons"][0] == (
        "V3.5 independent preselection producers have not materialized this date."
    )
    assert base_store.read_payload("20260730") == base
    assert len(base_store.read_payload("20260730")["rows"]) == 5
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_stage_input_uses_frozen_base259_only_and_excludes_overlay43(tmp_path: Path) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    frozen = contract["frozen_inputs"]
    fixture_manifest = json.loads(OPTIONAL_FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    base_path = OPTIONAL_FIXTURE_ROOT / fixture_manifest["base_payload"]["relative_path"]
    overlay_path = OPTIONAL_FIXTURE_ROOT / fixture_manifest["overlay_payload"]["relative_path"]
    assert _sha256(base_path) == frozen["v35_base_payload"]["raw_sha256"]
    assert _sha256(base_path) == fixture_manifest["base_payload"]["sha256"]
    assert _sha256(overlay_path) == fixture_manifest["overlay_payload"]["sha256"]
    base = json.loads(base_path.read_text(encoding="utf-8"))
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert len(base["rows"]) == fixture_manifest["base_payload"]["row_count"]
    wechat_rows = next(
        pool["rows"]
        for pool in overlay["pools"]
        if pool["pool_id"] == "wechat_public_account_v3_preselect"
    )
    assert len(wechat_rows) == fixture_manifest["overlay_payload"]["row_count"]

    data_store = NativeDataStore(tmp_path / "data")
    data_store.import_payload(base)
    PreselectionOverlayStore(data_store.root).import_overlay(overlay)

    class QuoteSpy:
        def __init__(self) -> None:
            self.requested: tuple[str, ...] = ()

        def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
            self.requested = tuple(symbols)
            return {
                "schema_version": "v3_5.read_only_quote_batch.v1",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "captured_at": "2026-07-30T09:25:05",
                "temporal_cutoff_safe": True,
                "source": "FROZEN_BASE259_STAGE_INPUT_SPY",
                "rows": [{"symbol": symbol} for symbol in symbols],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    provider = QuoteSpy()
    stage_store = StageStore(data_store.root)
    StageInputProducer(data_store, stage_store, provider).produce(
        "20260730", "STAGE_0925"
    )
    stage_input, _ = stage_store.read_input("20260730", "STAGE_0925")
    base_symbols = {str(row["symbol"]) for row in base["rows"]}
    wechat_only = {str(row["symbol"]) for row in wechat_rows} - base_symbols

    assert sum(symbol.startswith("A.") for symbol in provider.requested) == 147
    assert sum(symbol.startswith("HK.") for symbol in provider.requested) == 100
    assert set(provider.requested).isdisjoint(wechat_only)
    assert stage_input["source_summary"]["requested_A"] == 147
    assert stage_input["source_summary"]["requested_HK"] == 100
    assert all(
        row.get("pool_id") != "wechat_public_account_v3_preselect"
        for market_rows in stage_input["rows"].values()
        for row in market_rows
    )


def test_missing_independent_artifacts_fail_closed_without_optional_placeholders(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    NativeDataStore(data_root).import_payload(_base_payload("20260730"))
    body = TestClient(create_app(data_root=data_root)).get(
        "/api/v3/preselection-pools", params={"date": "20260730"}
    ).json()
    assert body["ok"] is False
    assert body["pools"] == []
    assert body["row_count"] == 0
    assert body["blocking_reasons"][0] == (
        "V3.5 independent preselection producers have not materialized this date."
    )
