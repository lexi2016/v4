from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

from domains.opening_second_filter import (
    MODEL_ID,
    build_v11_opening_second_filter,
)
from domains.stages import StageRunner
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import ALLOWED_WORKLOAD_IDS
from infrastructure.stage_store import StageStore
from ops.import_opening_second_filter_v11 import import_legacy_v11_files
from ops import run_scheduled_slot, run_stage_center_tick
from ops import run_v35_macos_scheduler


def _preselect_rows(count: int = 20) -> list[dict]:
    return [
        {
            "code": f"HK.{index:05d}",
            "name": f"股票{index}",
            "stage_rank": index,
            "source_lane": "D1_PRESELECT",
        }
        for index in range(1, count + 1)
    ]


def _auction_rows(count: int = 20) -> list[dict]:
    rows = []
    for index in range(1, count + 1):
        score = 100 - index
        rows.append(
            {
                "code": f"HK.{index:05d}",
                "stage1_ref_score": score,
                "stage1_ref_label": "竞价优先观察",
                "auction_ref_gap_pct": 3.0,
                "visible_depth_hkd": 2_000_000,
                "spread_pct": 0.5,
                "last_price": 10 + index / 10,
                "prev_close_price": 10,
                "turnover": 1_000_000 + index,
                "collector_wall_time": "2026-07-30 09:19:40",
            }
        )
    return rows


def _source_evidence() -> dict[str, str]:
    return {
        "d1_pool_sha256": "a" * 64,
        "auction_source_sha256": "b" * 64,
        "source_output_sha256": "c" * 64,
    }


def _stage_input() -> dict:
    return {
        "schema_version": "v3_5.stage_input.v1",
        "trade_date": "20260730",
        "stage_id": "STAGE_0925",
        "cutoff_reached": True,
        "market_status": {"A": "READY", "HK": "READY"},
        "rows": {
            "A": [
                {
                    "symbol": "A.000001",
                    "open_price": 11,
                    "last_price": 11,
                    "prev_close_price": 10,
                    "turnover": 20_000_000,
                    "pool_score": 100,
                    "recommendation_status": "WATCH_ONLY",
                }
            ],
            "HK": [
                {
                    "symbol": "HK.99999",
                    "pct_chg": 1,
                    "turnover_hkd_yi": 0.1,
                    "recommendation_status": "WATCH_ONLY",
                }
            ],
        },
        "source_evidence": [{"path": "imports/stage.json", "sha256": "d" * 64}],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }


def test_v11_champion_reproduces_frozen_top20_rerank_contract() -> None:
    auction_rows = _auction_rows()
    auction_rows[4]["stage1_ref_score"] = 76
    auction_rows[4]["code"] = "HK.02685"
    preselect_rows = _preselect_rows()
    preselect_rows[4].update(code="HK.02685", name="量化派")

    artifact = build_v11_opening_second_filter(
        preselect_rows,
        auction_rows,
        trade_date="20260730",
        signal_date="20260729",
        source_evidence=_source_evidence(),
    )

    assert artifact["model_id"] == MODEL_ID == "hkconnect_opening_second_filter_v1_1"
    assert artifact["champion_contract"] == "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer"
    assert artifact["signal_cutoff"] == "09:19:59"
    assert artifact["publication_time"] == "09:20:00"
    assert artifact["status"] == "AUCTION_SECOND_FILTER_READY"
    assert len(artifact["rows"]) == 20
    row = next(item for item in artifact["rows"] if item["code"] == "HK.02685")
    assert row["auction_score"] == 76
    assert row["second_filter_status"] == "AUCTION_SECOND_FILTER_PRIORITY"
    assert row["recommendation_status"] == "WATCH_ONLY"
    assert artifact["production_allowed"] is False
    assert artifact["orders_sent"] is False


def test_offline_v11_import_verifies_csv_sha_and_removes_old_runtime_paths(tmp_path) -> None:
    csv_path = tmp_path / "legacy_v11.csv"
    legacy_rows = build_v11_opening_second_filter(
        _preselect_rows(),
        _auction_rows(),
        trade_date="20260730",
        signal_date="20260729",
        source_evidence=_source_evidence(),
    )["rows"]
    fieldnames = sorted({key for row in legacy_rows for key in row})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(legacy_rows)
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    acceptance_path = tmp_path / "acceptance.json"
    acceptance_path.write_text(
        json.dumps(
            {
                "schema_version": "hkconnect_0920_auction_second_filter.v2",
                "status": "AUCTION_SECOND_FILTER_READY",
                "target_date": "20260730",
                "signal_date": "20260729",
                "row_count": 20,
                "required_row_count": 20,
                "signal_cutoff": "09:19:59",
                "publication_time": "09:20:00",
                "preselect_row_count": 100,
                "auction_row_count": 50,
                "preselect_sha256": "a" * 64,
                "auction_source_sha256": "b" * 64,
                "csv_sha256": csv_sha,
                "csv_path": r"C:\Users\huang\Desktop\学习\v3_system\legacy.csv",
                "production_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = OpeningSecondFilterStore(tmp_path / "data")

    result = import_legacy_v11_files(store, acceptance_path, csv_path)
    artifact = store.read("20260730")

    assert result["row_count"] == 20
    assert artifact is not None
    assert artifact["source_evidence"]["source_output_sha256"] == csv_sha
    assert "v3_system" not in json.dumps(artifact, ensure_ascii=False).lower()


def test_stage_0925_uses_v11_champion_rows_instead_of_native_hk_ranker(tmp_path) -> None:
    root = tmp_path / "data"
    stage_store = StageStore(root)
    stage_store.import_input(_stage_input())
    v11_store = OpeningSecondFilterStore(root)
    v11_store.publish(
        build_v11_opening_second_filter(
            _preselect_rows(),
            _auction_rows(),
            trade_date="20260730",
            signal_date="20260729",
            source_evidence=_source_evidence(),
        )
    )
    runner = StageRunner(stage_store, opening_second_filter_store=v11_store)
    runner.ensure("20260730", "STAGE_0925")

    workbench = runner.read_workbench("20260730", "STAGE_0925", limit=20)

    assert workbench["selection_mode"] == "V1_1_CHAMPION_DUAL_MARKET"
    assert workbench["opening_second_filter"]["model_id"] == MODEL_ID
    assert workbench["opening_second_filter"]["status"] == "AUCTION_SECOND_FILTER_READY"
    assert workbench["selected_a_rows"] == 1
    assert workbench["selected_hk_rows"] == 20
    a_row = next(row for row in workbench["unified_rows"] if row["market"] == "A")
    assert a_row["model_id"] == MODEL_ID
    assert a_row["opening_second_filter_strategy"] == "a_share_v1_1_price_volume_adapter"
    assert a_row["opening_second_filter_score"] > 0
    hk_rows = [row for row in workbench["unified_rows"] if row["market"] == "HK"]
    assert hk_rows[0]["code"] == "HK.00001"
    assert hk_rows[0]["score"] == 99
    assert all(row["recommendation_status"] == "WATCH_ONLY" for row in hk_rows)
    assert "v3_system" not in json.dumps(workbench, ensure_ascii=False).lower()


def test_hk_0920_capture_is_a_registered_pre_stage_workload() -> None:
    catalog = load_workload_catalog()
    workload = next(
        row for row in catalog.workloads if row.workload_id == "hk_auction_0920"
    )

    assert workload.enabled is True
    assert workload.slots == ("0915",)
    assert workload.market_scope.value == "HK_CONNECT"
    assert workload.run_policy.value == "HK_CONNECT_TRADE_DAY"
    assert "ops.run_hkconnect_0915_0920_capture" in workload.command
    assert "0915" in run_scheduled_slot.ALL_SLOTS
    assert "hk_auction_0920" in ALLOWED_WORKLOAD_IDS


def test_macos_scheduler_resolves_hk_0915_exact_or_bounded_catchup(tmp_path: Path) -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    exact = run_v35_macos_scheduler.resolve_due_slot(
        ledger_root=tmp_path,
        now=datetime(2026, 8, 21, 9, 15, tzinfo=shanghai),
    )
    assert exact["observed_slot"] == "0915"
    assert exact["slot"] == "0915"
    assert exact["catchup"] is False

    for minute in (14, 20):
        other = run_v35_macos_scheduler.resolve_due_slot(
            ledger_root=tmp_path / f"minute-{minute}",
            now=datetime(2026, 8, 21, 9, minute, tzinfo=shanghai),
        )
        assert other["observed_slot"] == f"09{minute:02d}"
        assert other["slot"] != "0915"

    for minute in (16, 19):
        catchup = run_v35_macos_scheduler.resolve_due_slot(
            ledger_root=tmp_path / f"catchup-{minute}",
            now=datetime(2026, 8, 21, 9, minute, tzinfo=shanghai),
        )
        assert catchup["slot"] == "0915"
        assert catchup["catchup"] is True


def test_stage_weekend_gate_precedes_hk_universe_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config: dict[str, str] = {}
    for key in run_stage_center_tick.ALL_ROOTS:
        path = tmp_path / key
        if key == "python_path":
            path = Path(sys.executable)
        else:
            path.mkdir()
        config[key] = str(path)
    config_path = tmp_path / "stage-center.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    preflight_called: list[bool] = []
    monkeypatch.setattr(
        run_stage_center_tick,
        "_run_universe_preflight",
        lambda *args, **kwargs: preflight_called.append(True)
        or {"status": "CANNOT_CONFIRM", "error": "must not run on weekend"},
    )

    rc = run_stage_center_tick.main(
        [
            "--config",
            str(config_path),
            "--trade-date",
            "20260822",
            "--historical-backfill",
            "--evaluated-at",
            datetime(2026, 8, 22, 9, 15).isoformat(),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "NON_TRADING_DAY"
    assert payload["trade_date"] == "20260822"
    assert preflight_called == []
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
