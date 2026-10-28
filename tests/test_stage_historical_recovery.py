from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stage_center.selection import SelectionStore


TRADE_DATE = "20260930"
STAGE_ID = "STAGE_0935_0940"
MARKET = "A_SHARE"


def _selection_envelope(
    trade_date: str = TRADE_DATE,
    stage_id: str = STAGE_ID,
    market: str = MARKET,
    *,
    code: str = "A.000001",
    marker: str = "recovery_mode=HISTORICAL_BACKFILL",
) -> dict[str, Any]:
    from stage_center.contracts import SELECTION_ALGORITHM_ID
    from stage_center.selection import ALGORITHM_SHA256

    return {
        "schema_version": "stage_center.selection.v2",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "algorithm_id": SELECTION_ALGORITHM_ID,
        "algorithm_sha256": ALGORITHM_SHA256,
        "raw_artifact_sha256": "a" * 64,
        "source_status": "READY",
        "selection_status": "PARTIAL_WITH_ROWS",
        "requested_rows": 10,
        "source_rows": 1,
        "selected_rows": 1,
        "coverage_ratio": 0.1,
        "missing_symbols": [],
        "rows": [{"code": code, "rank": 1, "name": "示例"}],
        "source_evidence": [marker],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_runner_receipt(
    root: Path,
    run_id: str,
    envelope: dict[str, Any],
    published: dict[str, Any],
) -> None:
    receipt_path = root / "backfill" / run_id / TRADE_DATE / STAGE_ID / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_center.runner.receipt.v1",
                "runner": "stage_center",
                "mode": "BACKFILL",
                "backfill_run_id": run_id,
                "due_status": "HISTORICAL_BACKFILL",
                "trade_date": TRADE_DATE,
                "stage_id": STAGE_ID,
                "latest_updated": False,
                "current_updated": False,
                "write_performed": True,
                "markets": {
                    MARKET: {
                        "run_id": published["run_id"],
                        "artifact_id": published["artifact_id"],
                        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                        "selection_status": envelope["selection_status"],
                    }
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _consumer(selection_root: Path, receipt_root: Path | None = None):
    from stage_center.consumer import StageSelectionConsumer

    return StageSelectionConsumer(selection_root, runner_receipt_root=receipt_root)


def test_backfill_fallback_keeps_rows_and_marks_missing_runner_receipt(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    run_id = "recovery-r3"
    backfill_root = selection_root / "backfill" / run_id
    envelope = _selection_envelope()
    SelectionStore(backfill_root).publish(envelope, market=MARKET)

    result = _consumer(selection_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["rows"][0]["code"] == "A.000001"
    assert market["selection_mode"] == "BACKFILL"
    assert market["backfill_run_id"] == run_id
    assert market["selection_manifest_receipt_verified"] is True
    assert market["runner_receipt_verified"] is False
    assert market["runner_receipt_status"] == "CANNOT_CONFIRM"
    assert "BACKFILL_RUNNER_RECEIPT_CANNOT_CONFIRM" in market["cannot_confirm"]


def test_backfill_runner_receipt_must_match_exact_selection_identity(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    receipt_root = tmp_path / "receipts"
    run_id = "recovery-r4"
    envelope = _selection_envelope()
    published = SelectionStore(selection_root / "backfill" / run_id).publish(
        envelope, market=MARKET
    )
    _write_runner_receipt(receipt_root, run_id, envelope, published)

    result = _consumer(selection_root, receipt_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["runner_receipt_verified"] is True
    assert market["runner_receipt_status"] == "VERIFIED"
    assert len(market["runner_receipt_sha256"]) == 64
    assert "BACKFILL_RUNNER_RECEIPT_CANNOT_CONFIRM" not in market["cannot_confirm"]


def test_backfill_reader_uses_exact_date_stage_and_market(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    run_id = "wrong-date-r1"
    wrong_date = _selection_envelope(trade_date="20260929")
    SelectionStore(selection_root / "backfill" / run_id).publish(
        wrong_date, market=MARKET
    )

    result = _consumer(selection_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["status"] == "CANNOT_CONFIRM"
    assert market["rows"] == []
    assert market.get("selection_mode") is None


def test_runner_historical_market_allowlist_limits_one_lane_and_keeps_default(tmp_path: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from stage_center.runner import RunnerConfig, StageCenterRunner

    evaluated_at = datetime(2026, 9, 30, 9, 40, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    scoped_config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "missing-candidate-scoped",
        raw_root=tmp_path / "raw-scoped",
        selection_root=tmp_path / "selection-scoped",
        receipt_root=tmp_path / "receipts-scoped",
    )
    scoped = StageCenterRunner(scoped_config).tick(
        TRADE_DATE,
        evaluated_at,
        stage_id=STAGE_ID,
        historical_backfill=True,
        historical_markets=(MARKET,),
    )

    default_config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "missing-candidate-default",
        raw_root=tmp_path / "raw-default",
        selection_root=tmp_path / "selection-default",
        receipt_root=tmp_path / "receipts-default",
    )
    default = StageCenterRunner(default_config).tick(
        TRADE_DATE,
        evaluated_at,
        stage_id=STAGE_ID,
        historical_backfill=True,
    )

    assert tuple(scoped["markets"]) == (MARKET,)
    assert tuple(default["markets"]) == ("A_SHARE", "HK_CONNECT")
    assert scoped["mode"] == default["mode"] == "BACKFILL"
    assert scoped["latest_updated"] is default["latest_updated"] is False
    assert not (scoped_config.selection_root / "selection_latest.json").exists()
    assert not (default_config.selection_root / "selection_latest.json").exists()


def test_runner_rejects_historical_market_filter_outside_recovery_route(tmp_path: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import pytest

    from stage_center.runner import RunnerConfig, RunnerError, StageCenterRunner

    runner = StageCenterRunner(
        RunnerConfig(
            candidate_acquisition_root=tmp_path / "missing-candidate",
            raw_root=tmp_path / "raw",
            selection_root=tmp_path / "selection",
            receipt_root=tmp_path / "receipts",
        )
    )
    with pytest.raises(RunnerError, match="requires historical_backfill"):
        runner.tick(
            TRADE_DATE,
            datetime(2026, 9, 30, 9, 40, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
            stage_id=STAGE_ID,
            historical_markets=(MARKET,),
        )
    assert not (tmp_path / "receipts").exists()


def test_ordinary_verified_lane_precedes_backfill(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    natural = _selection_envelope(marker="natural-stage-result")
    natural["selection_status"] = "READY"
    ordinary = SelectionStore(selection_root).publish(natural, market=MARKET)
    backfill = _selection_envelope(code="A.000002")
    SelectionStore(selection_root / "backfill" / "recovery-r5").publish(
        backfill, market=MARKET
    )

    result = _consumer(selection_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["run_id"] == ordinary["run_id"]
    assert market["rows"][0]["code"] == "A.000001"
    assert market.get("selection_mode") is None


def test_conflicting_backfill_batches_fail_closed(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    for run_id, code in (("recovery-r6", "A.000001"), ("recovery-r7", "A.000002")):
        SelectionStore(selection_root / "backfill" / run_id).publish(
            _selection_envelope(code=code), market=MARKET
        )

    result = _consumer(selection_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["status"] == "CANNOT_CONFIRM"
    assert market["rows"] == []
    assert "BACKFILL_NAMESPACE_CONFLICT" in market["cannot_confirm"]


def test_identical_backfill_selection_is_visible_with_batch_conflict(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    envelope = _selection_envelope()
    for run_id in ("recovery-identical-a", "recovery-identical-b"):
        SelectionStore(selection_root / "backfill" / run_id).publish(
            envelope, market=MARKET
        )

    result = _consumer(selection_root).get(
        TRADE_DATE, STAGE_ID, markets=(MARKET,), allow_backfill=True
    )

    market = result["markets"][MARKET]
    assert market["rows"][0]["code"] == "A.000001"
    assert market["selection_mode"] == "BACKFILL"
    assert market["backfill_run_id"] is None
    assert market["backfill_run_ids"] == ["recovery-identical-a", "recovery-identical-b"]
    assert market["runner_receipt_verified"] is False
    assert market["runner_receipt_status"] == "CANNOT_CONFIRM"
    assert "BACKFILL_NAMESPACE_CONFLICT" in market["cannot_confirm"]


def test_stage_workbench_api_preserves_backfill_provenance(tmp_path: Path) -> None:
    from apps.api.v35_api.app import create_app
    from infrastructure.data_store import NativeDataStore

    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": TRADE_DATE,
            "stage_dates": [],
            "future_target_dates": [],
            "materialized_rows": {},
        }
    )
    selection_root = tmp_path / "selection"
    SelectionStore(selection_root / "backfill" / "api-r1").publish(
        _selection_envelope(), market=MARKET
    )
    app = create_app(
        data_root=store.root,
        stage_center_selection_root=selection_root,
        current_date=TRADE_DATE,
    )
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/v3/workbench/stage"
    )

    result = endpoint(date=TRADE_DATE, stage=STAGE_ID, limit=50)

    assert result["markets"]["A"]["selection_mode"] == "BACKFILL"
    assert result["markets"]["A"]["backfill_run_id"] == "api-r1"
    assert result["markets"]["A"]["runner_receipt_verified"] is False
    assert result["markets"]["A"]["candidate_count"] == 1
    assert result["unified_rows"][0]["code"] == "A.000001"
