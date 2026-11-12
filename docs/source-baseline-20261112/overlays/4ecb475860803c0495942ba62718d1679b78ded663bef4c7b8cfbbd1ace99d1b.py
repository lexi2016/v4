from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as parquet
import pytest
from fastapi.testclient import TestClient

from apps.api.v4_api.app import create_app
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionStore, publish_selection, select_a_stage, select_hk_four_lane


TRADE_DATE = "20260821"
STAGE_ID = "STAGE_0930_0935"


def _a_source_row(code: str, name: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "first_open": 10.0,
        "last_close": 10.2,
        "high": 10.4,
        "low": 9.9,
        "amount": 1_000_000,
        "bar_count": 5,
        "expected_rows": 5,
    }
    if name is not None:
        row["name"] = name
    return row


def _hk_source_row(code: str = "HK.00001") -> dict[str, object]:
    return {
        "code": code,
        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        "platform_circular_market_cap_hkd_yi": 80.0,
        "offer_float_market_cap_hkd_yi": 15.0,
        "pct_chg": 4.0,
        "volume_ratio": 1.5,
        "turnover_hkd_yi": 0.2,
        "turnover_rate": 3.0,
        "stage_id": STAGE_ID,
    }


def _publish_a(root: Path, *, names: tuple[str | None, ...] = (None, None, None)) -> dict[str, Any]:
    rows = [
        _a_source_row(f"A.{index:06d}", name)
        for index, name in enumerate(names, start=1)
    ]
    envelope = select_a_stage(rows, TRADE_DATE, STAGE_ID, "a" * 64)
    publish_selection(root, envelope, market="A_SHARE")
    return envelope


def _publish_hk(root: Path) -> None:
    envelope = select_hk_four_lane([_hk_source_row()], TRADE_DATE, STAGE_ID, "b" * 64)
    publish_selection(root, envelope, market="HK_CONNECT")


def _authority_fixture(
    root: Path,
    *,
    receipt_shape: str = "READY",
    receipt_date: str = TRADE_DATE,
    lane_date: str = TRADE_DATE,
    formula_date: str = TRADE_DATE,
    selector_path: Path | None = None,
    selector_columns: tuple[str, ...] = ("trade_date", "ts_code", "name"),
    selector_rows: list[dict[str, object]] | None = None,
    selector_sha: str | None = None,
    include_selector_sha: bool = True,
    receipt_safety: dict[str, bool] | None = None,
    lane_safety: dict[str, bool] | None = None,
) -> tuple[Path, Path, Path]:
    """Build state/research_panel_daily/receipts and state/workspace fixtures."""
    state_root = root / "state"
    receipt_root = state_root / "research_panel_daily" / "receipts"
    selector = selector_path or state_root / "workspace" / "selector.parquet"
    selector.parent.mkdir(parents=True, exist_ok=True)
    rows = selector_rows or [
        {"trade_date": TRADE_DATE, "ts_code": "000001.SZ", "name": "甲公司"},
        {"trade_date": TRADE_DATE, "ts_code": "000002.SZ", "name": "乙公司"},
        {"trade_date": TRADE_DATE, "ts_code": "000003.SZ", "name": "丙公司"},
    ]
    values = {column: [row.get(column) for row in rows] for column in selector_columns}
    parquet.write_table(pa.table(values), selector)
    actual_sha = hashlib.sha256(selector.read_bytes()).hexdigest()
    formula: dict[str, object] = {
        "status": "READY",
        "target_date": formula_date,
        "selector": str(selector),
    }
    if include_selector_sha:
        formula["selector_sha256"] = selector_sha if selector_sha is not None else actual_sha
    safe = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    lane = {
        "status": "READY",
        "target_date": lane_date,
        "formula": formula,
        **safe,
        **(lane_safety or {}),
    }
    if receipt_shape == "ATTEMPTED":
        receipt: dict[str, object] = {
            "status": "ATTEMPTED",
            "target_date": receipt_date,
            "lanes": {"A": lane},
            **safe,
            **(receipt_safety or {}),
        }
    else:
        receipt = {
            "status": "READY",
            "target_date": receipt_date,
            "formula": formula,
            **safe,
            **(receipt_safety or {}),
        }
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_root / f"a-{TRADE_DATE}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    return state_root, receipt_path, selector


def _consumer_fixture(
    tmp_path: Path,
    *,
    names: tuple[str | None, ...] = (None, None, None),
    **authority_kwargs: object,
) -> tuple[StageSelectionConsumer, Path, dict[str, Any], Path, Path]:
    selection_root = tmp_path / "selection"
    original = _publish_a(selection_root, names=names)
    state_root, receipt_path, selector_path = _authority_fixture(tmp_path, **authority_kwargs)
    consumer = StageSelectionConsumer(
        selection_root,
        a_name_authority_root=state_root / "research_panel_daily" / "receipts",
    )
    return consumer, selection_root, original, receipt_path, selector_path


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_ready_overlay_fills_missing_names_only_and_preserves_identity_order_score_status(tmp_path: Path) -> None:
    consumer, selection_root, _original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, names=(None, "已有名", None)
    )
    before = _file_hashes(selection_root)
    verified = SelectionStore(selection_root).read_verified(TRADE_DATE, STAGE_ID, "A_SHARE")
    response = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))
    after = _file_hashes(selection_root)
    market = response["markets"]["A_SHARE"]

    assert before == after
    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_applied_count"] == 2
    assert market["name_authority_missing_count"] == 0
    assert market["name_authority_receipt_sha256"]
    assert market["name_authority_selector_sha256"]
    assert market["name_authority_selector_sha_source"] == "DECLARED_AND_VERIFIED"
    assert [row["name"] for row in market["rows"]] == ["甲公司", "已有名", "丙公司"]
    assert [row["stock_name"] for row in market["rows"]] == ["甲公司", "已有名", "丙公司"]
    assert market["artifact_id"] == verified["artifact_id"]
    assert market["run_id"] == verified["run_id"]
    assert market["algorithm_sha256"] == verified["algorithm_sha256"]
    assert market["raw_artifact_sha256"] == verified["raw_artifact_sha256"]
    assert market["selection_status"] == verified["selection_status"]
    assert [(row["code"], row["order"], row["rank"], row["score"], row["status"]) for row in market["rows"]] == [
        (row["code"], index, row["rank"], row["score"], row["status"])
        for index, row in enumerate(verified["rows"], start=1)
    ]


def test_attempted_lane_overlay_is_cached_for_repeated_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, _selection_root, _original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, receipt_shape="ATTEMPTED"
    )
    calls = 0
    original_read_table = parquet.read_table

    def counted_read_table(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original_read_table(*args, **kwargs)

    monkeypatch.setattr(parquet, "read_table", counted_read_table)
    first = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))
    second = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))

    assert calls == 1
    assert first["markets"]["A_SHARE"]["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert second["markets"]["A_SHARE"]["rows"][0]["name"] == "甲公司"


def test_overlay_reads_schema_then_filtered_required_columns_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer, _selection_root, _original, _receipt_path, _selector_path = _consumer_fixture(tmp_path)
    events: list[Any] = []
    original_read_schema = parquet.read_schema
    original_read_table = parquet.read_table

    def counted_read_schema(*args: Any, **kwargs: Any) -> Any:
        events.append("schema")
        return original_read_schema(*args, **kwargs)

    def counted_read_table(*args: Any, **kwargs: Any) -> Any:
        events.append(("table", kwargs))
        return original_read_table(*args, **kwargs)

    monkeypatch.setattr(parquet, "read_schema", counted_read_schema)
    monkeypatch.setattr(parquet, "read_table", counted_read_table)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert events[0] == "schema"
    assert events[1][0] == "table"
    assert events[1][1]["columns"] == ["trade_date", "ts_code", "name"]
    assert events[1][1]["filters"] == [("trade_date", "=", TRADE_DATE)]


def test_overlay_computes_selector_sha_when_receipt_does_not_declare_it(tmp_path: Path) -> None:
    consumer, _selection_root, _original, _receipt_path, selector_path = _consumer_fixture(
        tmp_path, include_selector_sha=False
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["name_authority_selector_sha256"] == hashlib.sha256(selector_path.read_bytes()).hexdigest()
    assert market["name_authority_selector_sha_source"] == "COMPUTED_FROM_AUTHORITY_PATH"


def test_failed_authority_read_is_not_cached_and_recovers_after_receipt_arrives(tmp_path: Path) -> None:
    consumer, _selection_root, _original, receipt_path, _selector_path = _consumer_fixture(tmp_path)
    receipt_bytes = receipt_path.read_bytes()
    receipt_path.unlink()

    first = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]
    assert first["name_authority_status"] == "CANNOT_CONFIRM"

    receipt_path.write_bytes(receipt_bytes)
    second = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]
    assert second["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert second["rows"][0]["name"] == "甲公司"


@pytest.mark.parametrize("bad_part", ("receipt", "lane", "formula"))
def test_overlay_wrong_date_is_fail_closed_without_selection_status_change(
    tmp_path: Path, bad_part: str
) -> None:
    kwargs: dict[str, object] = {"receipt_shape": "ATTEMPTED"}
    if bad_part == "receipt":
        kwargs["receipt_date"] = "20260820"
    elif bad_part == "lane":
        kwargs["lane_date"] = "20260820"
    else:
        kwargs["formula_date"] = "20260820"
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(tmp_path, **kwargs)
    response = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))
    market = response["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert [(row["name"], row["stock_name"]) for row in market["rows"]] == [(None, None)] * 3


@pytest.mark.parametrize("level", ("receipt", "lane"))
def test_overlay_safety_flags_fail_closed(tmp_path: Path, level: str) -> None:
    kwargs = {
        "receipt_shape": "ATTEMPTED",
        f"{level}_safety": {"orders_sent": True},
    }
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(tmp_path, **kwargs)
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert market["rows"][0]["name"] is None


def test_overlay_selector_outside_state_authority_root_fails_closed(tmp_path: Path) -> None:
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path,
        selector_path=tmp_path / "outside-state" / "selector.parquet",
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert market["rows"][0]["name"] is None


def test_overlay_selector_sha_mismatch_fails_closed(tmp_path: Path) -> None:
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, selector_sha="0" * 64
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert market["rows"][1]["name"] is None


@pytest.mark.parametrize("columns", (("trade_date", "ts_code"), ("trade_date", "name")))
def test_overlay_selector_schema_mismatch_fails_closed(tmp_path: Path, columns: tuple[str, ...]) -> None:
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, selector_columns=columns
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["selection_status"] == original["selection_status"]
    assert all(row["name"] is None for row in market["rows"])


def test_overlay_reads_only_exact_trade_date_rows(tmp_path: Path) -> None:
    selector_rows = [
        {"trade_date": "20260820", "ts_code": "000001.SZ", "name": "旧日期名"},
        {"trade_date": TRADE_DATE, "ts_code": "000001.SZ", "name": "甲公司"},
        {"trade_date": TRADE_DATE, "ts_code": "000002.SZ", "name": "乙公司"},
        {"trade_date": TRADE_DATE, "ts_code": "000003.SZ", "name": "丙公司"},
    ]
    consumer, _selection_root, _original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, selector_rows=selector_rows
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert market["rows"][0]["name"] == "甲公司"


def test_overlay_does_not_read_authority_when_no_name_is_missing(tmp_path: Path) -> None:
    consumer, _selection_root, _original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, names=("已有一", "已有二", "已有三")
    )
    consumer.a_name_authority_root = tmp_path / "missing-authority-root"
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "NOT_NEEDED"
    assert market["name_authority_applied_count"] == 0
    assert market["name_authority_missing_count"] == 0
    assert [row["name"] for row in market["rows"]] == ["已有一", "已有二", "已有三"]


def test_overlay_missing_code_keeps_blank_name_and_records_not_found(tmp_path: Path) -> None:
    selector_rows = [{"trade_date": TRADE_DATE, "ts_code": "000001.SZ", "name": "甲公司"}]
    consumer, _selection_root, original, _receipt_path, _selector_path = _consumer_fixture(
        tmp_path, selector_rows=selector_rows
    )
    market = consumer.get(TRADE_DATE, STAGE_ID, markets=("A_SHARE",))["markets"]["A_SHARE"]

    assert market["name_authority_status"] == "CANNOT_CONFIRM"
    assert market["name_authority_applied_count"] == 1
    assert market["name_authority_missing_count"] == 2
    assert market["rows"][0]["name"] == "甲公司"
    assert market["rows"][1]["name"] is None
    assert "NAME_AUTHORITY_CODE_NOT_FOUND" in market["cannot_confirm"]
    assert market["selection_status"] == original["selection_status"]


def test_create_app_shared_mode_derives_authority_root_from_data_root(tmp_path: Path) -> None:
    selection_root = tmp_path / "selection"
    _publish_a(selection_root, names=(None, None, None))
    _publish_hk(selection_root)
    state_root, _receipt_path, _selector_path = _authority_fixture(tmp_path)
    client = TestClient(
        create_app(
            data_root=state_root / "data",
            stage_center_selection_root=selection_root,
            current_date=TRADE_DATE,
        )
    )

    response = client.get(
        "/api/v4/stage-center/selection",
        params={"date": TRADE_DATE, "stage": STAGE_ID},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["markets"]["A"]["name_authority_status"] == "EXACT_DATE_READ_OVERLAY"
    assert payload["markets"]["A"]["name_authority_selector_sha_source"] == "DECLARED_AND_VERIFIED"
    assert payload["markets"]["A"]["rows"][0]["name"] == "甲公司"
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
