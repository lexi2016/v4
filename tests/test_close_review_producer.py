from __future__ import annotations

import importlib
from datetime import datetime

from domains import close_review as close_review_domain
from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from stage_center.selection import ALGORITHM_SHA256, SelectionStore, select_hk_four_lane


STAGE_IDS = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
)


def test_review_percentages_are_stable_for_page_rendering() -> None:
    metric = close_review_domain._metric(
        [f"HK.{index:05d}" for index in range(1, 51)],
        {f"HK.{index:05d}" for index in range(1, 12)},
    )

    assert metric["coverage_pct"] == 55.0
    assert metric["precision_pct"] == 22.0


def test_native_review_ranks_full_close_universe_and_calculates_frozen_kpis() -> None:
    close_rows = [
        {
            "trade_date": "20260730",
            "code": f"HK.{index:05d}",
            "name": f"Stock {index}",
            "close": 100 + index,
            "pre_close": 100,
            "amount": index * 1_000,
        }
        for index in range(1, 26)
    ]
    model_rows = [
        {
            "market": "HK",
            "symbol": f"HK.{index:05d}",
            "stock_name": f"Stock {index}",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": index,
            "target_date": "20260730",
        }
        for index in range(1, 101)
    ]
    stage_rows = {
        stage_id: [
            {
                "market": "HK",
                "code": f"HK.{code:05d}",
                "name": f"Stock {code}",
                "rank": 1,
                "recommendation_status": "WATCH_ONLY",
            }
            for code in codes
        ]
        for stage_id, codes in zip(
            STAGE_IDS,
            ((25, 101), (24,), (23,), (22,), (21,), (20,), (19,)),
            strict=True,
        )
    }

    result = close_review_domain.build_native_close_review(
        "20260730",
        close_rows=close_rows,
        model_rows=model_rows,
        stage_rows=stage_rows,
        close_source_sha256="a" * 64,
    )

    assert result["schema_version"] == "v3_5.close_review.v1"
    assert result["status"] == "MODEL_REVIEW_READY"
    assert result["row_counts"] == {
        "hkconnect_universe": 25,
        "close_top20": 20,
        "model_0_2": 100,
        "stage_rows": 8,
    }
    assert [row["code"] for row in result["close_top20"][:3]] == [
        "HK.00025",
        "HK.00024",
        "HK.00023",
    ]
    assert result["models"]["0.2_prob_active"]["hit_count"] == 20
    assert result["models"]["0.2_prob_active"]["coverage_pct"] == 100.0
    assert result["models"]["0.2_prob_active"]["precision_pct"] == 20.0
    assert result["stage_union"]["selected_count"] == 8
    assert result["stage_union"]["hit_count"] == 7
    assert result["stage_union"]["coverage_pct"] == 35.0
    assert result["stage_union"]["precision_pct"] == 87.5
    assert result["top20_attribution"][0]["classification"] == "shared"
    assert result["close_source_sha256"] == "a" * 64
    assert result["reference_snapshot"] is False
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_close_snapshot_store_persists_full_universe_with_receipt(tmp_path) -> None:
    store_module = importlib.import_module("infrastructure.hkconnect_close_store")
    rows = [
        {
            "trade_date": "20260730",
            "code": f"HK.{index:05d}",
            "name": f"Stock {index}",
            "close": 100 + index,
            "pre_close": 100,
            "amount": index * 1_000,
        }
        for index in range(1, 601)
    ]
    payload = {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": "20260730",
        "status": "READY",
        "source_mode": "TDX_VIPDOC_DAILY_PANEL",
        "source_input_sha256": "b" * 64,
        "universe_count": 600,
        "same_date_row_count": 600,
        "coverage_ratio": 1.0,
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    store = store_module.CloseSnapshotStore(tmp_path / "data")

    written = store.import_snapshot(payload)
    loaded, digest = store.read_snapshot("20260730")

    assert loaded == payload
    assert digest == written["sha256"]
    assert written["payload_path"] == "hkconnect_close_snapshots/20260730.json"
    assert (tmp_path / "data" / written["receipt_path"]).is_file()


def test_vipdoc_normalizer_freezes_target_date_and_removes_external_paths() -> None:
    importer = importlib.import_module("ops.import_hkconnect_close_source")
    records = [
        {
            "trade_date": 20260730,
            "trade_date_compact": "20260730",
            "code_norm": f"HK.{index:05d}",
            "close": 100 + index,
            "pre_close": 100,
            "amount": index * 1_000,
            "source_path": rf"C:\external\71#{index:05d}.day",
        }
        for index in range(1, 601)
    ]

    payload = importer.normalize_vipdoc_rows(
        "20260730",
        records,
        source_input_sha256="c" * 64,
        name_map={"HK.00001": "长和"},
    )

    assert payload["universe_count"] == 600
    assert payload["same_date_row_count"] == 600
    assert payload["coverage_ratio"] == 1.0
    assert payload["rows"][0]["name"] == "长和"
    assert payload["rows"][0]["pct_chg_close"] == 1.0
    assert "source_path" not in str(payload)
    assert "external" not in str(payload)


def test_native_review_supersedes_blocked_reference_with_audit_receipt(tmp_path) -> None:
    store = ReviewStore(tmp_path / "data")
    blocked = {
        "schema_version": "v3_5.close_review_reference.v1",
        "trade_date": "20260730",
        "status": "BLOCKED_CLOSE_DATA",
        "primary_kpi": "全港股通收盘涨幅Top20覆盖率",
        "models": {},
        "stages": {},
        "stage_union": {},
        "kpi": {},
        "row_counts": {},
        "close_top20": [],
        "model_rows": [],
        "stage_rows": [],
        "top20_attribution": [],
        "missing_stages": [],
        "cannot_confirm": ["HKCONNECT_DAILY_REVIEW_NOT_FOUND"],
        "reference_snapshot": True,
        "write_policy": "review_only_read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    imported = store.import_reference(blocked)
    native = close_review_domain.build_native_close_review(
        "20260730",
        close_rows=[
            {
                "trade_date": "20260730",
                "code": f"HK.{index:05d}",
                "close": 100 + index,
                "pre_close": 100,
                "amount": index,
            }
            for index in range(1, 26)
        ],
        model_rows=[
            {
                "market": "HK",
                "symbol": f"HK.{index:05d}",
                "pool_rank": index,
                "target_date": "20260730",
            }
            for index in range(1, 101)
        ],
        stage_rows={stage_id: [] for stage_id in STAGE_IDS},
        close_source_sha256="d" * 64,
    )

    published = store.publish_native(native, expected_sha256=imported["sha256"])
    loaded = store.read_reference("20260730")

    assert loaded == native
    assert published["previous_sha256"] == imported["sha256"]
    assert published["sha256"] != imported["sha256"]
    assert (store.root / published["supersession_receipt_path"]).is_file()


def test_store_backed_producer_joins_close_model_and_seven_stage_inputs(tmp_path) -> None:
    producer = importlib.import_module("ops.build_close_review")
    data_root = tmp_path / "data"
    close_payload = {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": "20260730",
        "status": "READY",
        "source_mode": "TDX_VIPDOC_DAILY_PANEL",
        "source_input_sha256": "e" * 64,
        "universe_count": 600,
        "same_date_row_count": 600,
        "coverage_ratio": 1.0,
        "rows": [
            {
                "trade_date": "20260730",
                "code": f"HK.{index:05d}",
                "name": f"Stock {index}",
                "close": 100 + index,
                "pre_close": 100,
                "amount": index,
            }
            for index in range(1, 601)
        ],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    CloseSnapshotStore(data_root).import_snapshot(close_payload)
    model_rows = [
        {
            "market": "HK",
            "symbol": f"HK.{index:05d}",
            "stock_name": f"Stock {index}",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": index,
            "target_date": "20260730",
            "recommendation_status": "WATCH_ONLY",
        }
        for index in range(1, 101)
    ]
    preselection = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260730",
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK D-1 Top100",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "verified.test",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "fixture/hk.json",
        "source_sha256": "f" * 64,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "rows": model_rows,
        "cannot_confirm": [],
    }
    PreselectionPoolStore(data_root).materialize(preselection)
    stage_selection_root = data_root / "stage-selection"
    selection_store = SelectionStore(stage_selection_root)
    for offset, stage_id in enumerate(STAGE_IDS):
        row = {
            "code": f"HK.{600 - offset:05d}",
            "name": f"Stock {600 - offset}",
            "pct_chg": 1.0,
            "last_price": 101.0,
            "open_price": 100.0,
            "high_price": 101.0,
            "low_price": 100.0,
            "prev_close": 100.0,
            "turnover": 1000.0,
            "volume_ratio": 1.0,
        }
        selection_store.publish(
            select_hk_four_lane(
                [row],
                "20260730",
                stage_id,
                f"{offset + 1:064x}",
                source_evidence=("fixture=verified_stage_selection",),
            ),
            market="HK_CONNECT",
        )

    result = producer.build_close_review(
        data_root,
        "20260730",
        stage_selection_root=stage_selection_root,
    )
    served = ReviewStore(data_root).read_reference("20260730")

    assert served == result["review"]
    assert served["status"] == "MODEL_REVIEW_READY"
    assert served["row_counts"] == {
        "hkconnect_universe": 600,
        "close_top20": 20,
        "model_0_2": 100,
        "stage_rows": 7,
    }
    assert served["stage_union"]["hit_count"] == 7
    assert result["publication"]["payload_path"] == "close_reviews/20260730.json"


def test_futu_collector_materializes_same_day_full_universe_in_v35_store(tmp_path) -> None:
    collector = importlib.import_module("ops.collect_hkconnect_close_snapshot")

    class Frame:
        def __init__(self, rows):
            self.rows = rows

        def to_dict(self, *, orient):
            assert orient == "records"
            return self.rows

    class QuoteContext:
        def __init__(self):
            self.closed = False

        def get_plate_stock(self, plate_code):
            if plate_code == "HK.GangGuTong":
                rows = [
                    {"code": f"HK.{index:05d}", "stock_name": f"Stock {index}"}
                    for index in range(1, 601)
                ]
            else:
                rows = []
            return 0, Frame(rows)

        def get_market_snapshot(self, codes):
            return 0, Frame(
                [
                    {
                        "code": code,
                        "name": f"Stock {int(code[-5:])}",
                        "update_time": "2026-07-31 16:11:00",
                        "last_price": 100 + int(code[-5:]),
                        "prev_close_price": 100,
                        "turnover": int(code[-5:]) * 1_000,
                    }
                    for code in codes
                ]
            )

        def close(self):
            self.closed = True

    context = QuoteContext()
    result = collector.collect_close_snapshot(
        "20260731",
        data_root=tmp_path / "data",
        quote_context_factory=lambda: context,
        now=datetime(2026, 7, 31, 16, 11),
    )
    loaded, digest = CloseSnapshotStore(tmp_path / "data").read_snapshot("20260731")

    assert loaded["universe_count"] == 600
    assert loaded["same_date_row_count"] == 600
    assert loaded["source_mode"] == "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT"
    assert result["publication"]["sha256"] == digest
    assert context.closed is True
