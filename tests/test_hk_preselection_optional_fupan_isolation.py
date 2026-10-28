from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from ops import materialize_scheduled_preselection as scheduler


TRADE_DATE = "20261015"
SIGNAL_DATE = "20261014"
HK_POOL_ID = "hkconnect_d1_top100"
FUPAN_POOL_ID = "a_d1_fupan_watchlist_pool"


def _ready_hk_pool() -> dict:
    rows = [
        {
            "symbol": f"HK.{rank:05d}",
            "target_date": TRADE_DATE,
            "signal_date": SIGNAL_DATE,
        }
        for rank in range(1, 101)
    ]
    return {
        "trade_date": TRADE_DATE,
        "target_date": TRADE_DATE,
        "signal_date": SIGNAL_DATE,
        "pool_id": HK_POOL_ID,
        "display_name": "verified HK D-1 fixture",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "source_sha256": "b" * 64,
        "source_run_id": "verified-hk-fixture",
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _prepare_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fupan_bytes: bytes | None,
) -> tuple[list[dict], dict, Path, Path]:
    input_root = tmp_path / "inputs"
    day = input_root / TRADE_DATE
    day.mkdir(parents=True)
    fupan_path = day / "fupan.csv"
    manifest_path = day / "fupan.manifest.json"
    if fupan_bytes is not None:
        fupan_path.write_bytes(fupan_bytes)
        manifest_path.write_text(
            json.dumps(
                {
                    "status": "FUPAN_WATCHLIST_POOL_READY",
                    "fupan_pool_rule": "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW",
                    "target_date": TRADE_DATE,
                    "signal_date": SIGNAL_DATE,
                    "source_paths": ["verified-upstream/fupan.csv"],
                    "row_count": 0,
                    "cannot_confirm": [],
                }
            ),
            encoding="utf-8",
        )

    hk_pool = _ready_hk_pool()

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("unavailable fixture input")

    monkeypatch.setattr(scheduler, "build_shared_hk_0_2_pool", lambda *_args, **_kwargs: hk_pool)
    monkeypatch.setattr(scheduler, "build_shared_v192_premarket_pool", unavailable)
    monkeypatch.setattr(scheduler, "build_hourly_research_pool", unavailable)
    monkeypatch.setattr(scheduler, "load_baimao_preselection_pool", unavailable)

    artifacts = scheduler.build_scheduled_artifacts(
        trade_date=TRADE_DATE,
        signal_date=SIGNAL_DATE,
        selector=None,
        input_root=input_root,
        shared_data_root=tmp_path / "shared-data",
        shared_package_root=tmp_path / "shared-package",
        data_root=tmp_path / "data",
        market_scope="CROSS_MARKET",
    )
    return artifacts, hk_pool, fupan_path, manifest_path


def _assert_hk_remains_ready(artifacts: list[dict], expected_hk: dict) -> None:
    by_id = {item["pool_id"]: item for item in artifacts}
    assert by_id[HK_POOL_ID] == expected_hk
    assert by_id[HK_POOL_ID]["source_sha256"] == "b" * 64
    assert by_id[HK_POOL_ID]["target_date"] == TRADE_DATE
    assert by_id[HK_POOL_ID]["signal_date"] == SIGNAL_DATE
    assert by_id[HK_POOL_ID]["production_allowed"] is False
    assert by_id[HK_POOL_ID]["buy_gate_updated"] is False
    assert by_id[HK_POOL_ID]["orders_sent"] is False

    gate = scheduler._formal_pool_gate(
        artifacts,
        market_scope="CROSS_MARKET",
        hk_target_date=TRADE_DATE,
        hk_signal_date=SIGNAL_DATE,
    )
    assert gate["required"][HK_POOL_ID]["ready"] is True


def _assert_fupan_quarantined(artifacts: list[dict]) -> None:
    fupan = next(item for item in artifacts if item["pool_id"] == FUPAN_POOL_ID)
    assert fupan["status"] == "CANNOT_CONFIRM"
    assert fupan["rows"] == []
    assert fupan["production_allowed"] is False
    assert fupan["buy_gate_updated"] is False
    assert fupan["orders_sent"] is False


def test_invalid_utf8_fupan_is_quarantined_without_blocking_hk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_bytes = b"stock_code,stock_name,signal_date\n\xff,invalid,20261014\n"
    artifacts, hk_pool, fupan_path, manifest_path = _prepare_build(
        tmp_path, monkeypatch, fupan_bytes=csv_bytes
    )

    _assert_fupan_quarantined(artifacts)
    _assert_hk_remains_ready(artifacts, hk_pool)
    fupan = next(item for item in artifacts if item["pool_id"] == FUPAN_POOL_ID)
    observations = "\n".join(fupan["cannot_confirm"])
    assert f"{fupan_path}:sha256={hashlib.sha256(csv_bytes).hexdigest()}" in observations
    assert f"{manifest_path}:sha256=" in observations


def test_csv_field_limit_fupan_is_quarantined_without_blocking_hk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_bytes = (
        b"stock_code,stock_name,signal_date\n"
        + b"000001,fixture,"
        + b"x" * 256
        + b"\n"
    )
    original_field_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(128)
        artifacts, hk_pool, fupan_path, _manifest_path = _prepare_build(
            tmp_path, monkeypatch, fupan_bytes=csv_bytes
        )
    finally:
        csv.field_size_limit(original_field_limit)

    _assert_fupan_quarantined(artifacts)
    _assert_hk_remains_ready(artifacts, hk_pool)
    fupan = next(item for item in artifacts if item["pool_id"] == FUPAN_POOL_ID)
    observations = "\n".join(fupan["cannot_confirm"])
    assert f"{fupan_path}:sha256={hashlib.sha256(csv_bytes).hexdigest()}" in observations


def test_missing_fupan_remains_cannot_confirm_without_blocking_hk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, hk_pool, fupan_path, manifest_path = _prepare_build(
        tmp_path, monkeypatch, fupan_bytes=None
    )

    _assert_fupan_quarantined(artifacts)
    _assert_hk_remains_ready(artifacts, hk_pool)
    assert not fupan_path.exists()
    assert not manifest_path.exists()


def test_unknown_fupan_value_error_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, _hk_pool, fupan_path, manifest_path = _prepare_build(
        tmp_path,
        monkeypatch,
        fupan_bytes=b"stock_code,stock_name,signal_date\n000001,fixture,20261014\n",
    )
    assert artifacts

    def unexpected_safety_error(*_args, **_kwargs):
        raise ValueError("unrecognized source identity safety failure")

    monkeypatch.setattr(scheduler, "build_fupan_watchlist_pool", unexpected_safety_error)
    with pytest.raises(ValueError, match="unrecognized source identity safety failure"):
        scheduler.build_scheduled_artifacts(
            trade_date=TRADE_DATE,
            signal_date=SIGNAL_DATE,
            selector=None,
            input_root=fupan_path.parents[1],
            shared_data_root=tmp_path / "shared-data",
            shared_package_root=tmp_path / "shared-package",
            data_root=tmp_path / "data",
            market_scope="CROSS_MARKET",
        )
