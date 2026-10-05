"""Manager-only HK 15:55 PyTDX routing preserves all other slot defaults."""
from __future__ import annotations

from pathlib import Path

from scripts import acquire_stage_bundle as acquisition
from scripts.live_acquisition.contracts import StageSourceResult
from scripts.live_acquisition.universe import StageUniverse
from shared_data.hashing import sha256_json


TRADE_DATE = "20260806"
MODE = "PYTDX_LATE_OBSERVATION"


def _universe(market: str, codes: list[str], root: Path) -> StageUniverse:
    return StageUniverse(
        path=root / f"{market}.json",
        trade_date=TRADE_DATE,
        market=market,
        scope="FULL_MARKET" if market == "HK_CONNECT" else "STAGE_CANDIDATES",
        codes=tuple(codes),
        codes_sha256=sha256_json(codes),
        source_role="TEST_FIXED_UNIVERSE",
        source_sha256="a" * 64,
    )


def _row(code: str, stage_id: str) -> dict:
    if stage_id == "STAGE_1545_1555":
        update_time = "2026-08-06 15:55:00"
        window_start = "2026-08-06 15:46:00"
        window_end = "2026-08-06 15:55:00"
        bar_count = 10
    else:
        update_time = "2026-08-06 09:35:00"
        window_start = "2026-08-06 09:31:00"
        window_end = "2026-08-06 09:35:00"
        bar_count = 5
    return {
        "batch_index": 1,
        "code": code,
        "name": code,
        "update_time": update_time,
        "last_price": 10.0,
        "open_price": 10.0,
        "high_price": 10.0,
        "low_price": 10.0,
        "prev_close_price": 10.0,
        "turnover": 1000.0,
        "volume": 100.0,
        "bid_price": "",
        "ask_price": "",
        "bid_vol": "",
        "ask_vol": "",
        "window_start": window_start,
        "window_end": window_end,
        "bar_count": bar_count,
        "temporal_cutoff_safe": True,
    }


def test_manager_mode_routes_100_hk_codes_to_pytdx_only_at_1555(tmp_path, monkeypatch):
    store = tmp_path / "store"
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    hk_codes = [f"HK.{value:05d}" for value in range(1, 101)]
    a_codes = ["SH.600001"]
    universes = {
        "HK_CONNECT": _universe("HK_CONNECT", hk_codes, store),
        "A_SHARE": _universe("A_SHARE", a_codes, store),
    }
    monkeypatch.setattr(
        acquisition,
        "resolve_stage_universe",
        lambda _root, _date, market: universes[market],
    )
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", MODE)
    futu_calls: list[tuple[str, str, list[str]]] = []
    pytdx_calls: list[tuple[str, str, list[str]]] = []

    def result(source_id: str, stage_id: str, codes: list[str]) -> StageSourceResult:
        return StageSourceResult(
            source_id=source_id,
            display_name=source_id,
            status="READ_OK",
            fidelity=f"{source_id.upper()}_{stage_id}_CUTOFF_SAFE",
            rows=[_row(code, stage_id) for code in codes],
            requested_code_count=len(codes),
            completed_code_count=len(codes),
        )

    def futu_collector(_python, _date, stage_id, codes, *, market, process_runner, timeout_seconds=45):
        futu_calls.append((market, stage_id, list(codes)))
        return result("futu", stage_id, list(codes))

    def pytdx_collector(_python, _date, stage_id, codes, *, market, process_runner, timeout_seconds=45):
        pytdx_calls.append((market, stage_id, list(codes)))
        return result("pytdx", stage_id, list(codes))

    manager_result = acquisition.run_stage_bundle(
        store,
        TRADE_DATE,
        "STAGE_1545_1555",
        python,
        futu_collector=futu_collector,
        pytdx_collector=pytdx_collector,
    )
    assert manager_result["ok"] is True
    assert manager_result["markets"]["HK_CONNECT"]["source_id"] == "pytdx"
    assert futu_calls == []
    assert pytdx_calls == [("HK_CONNECT", "STAGE_1545_1555", hk_codes)]

    ordinary_result = acquisition.run_stage_bundle(
        store,
        TRADE_DATE,
        "STAGE_0930_0935",
        python,
        futu_collector=futu_collector,
        pytdx_collector=pytdx_collector,
    )
    assert ordinary_result["ok"] is True
    assert [(market, stage_id) for market, stage_id, _codes in futu_calls] == [
        ("A_SHARE", "STAGE_0930_0935"),
        ("HK_CONNECT", "STAGE_0930_0935"),
    ]
    assert len(pytdx_calls) == 1


def test_unknown_manager_mode_fails_closed_for_1555_before_collector(tmp_path, monkeypatch):
    store = tmp_path / "store"
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    hk_codes = [f"HK.{value:05d}" for value in range(1, 101)]
    monkeypatch.setattr(
        acquisition,
        "resolve_stage_universe",
        lambda _root, _date, _market: _universe("HK_CONNECT", hk_codes, store),
    )
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "unexpected-mode")
    calls = []

    try:
        acquisition.run_stage_bundle(
            store,
            TRADE_DATE,
            "STAGE_1545_1555",
            python,
            futu_collector=lambda *args, **kwargs: calls.append("futu"),
            pytdx_collector=lambda *args, **kwargs: calls.append("pytdx"),
        )
    except ValueError as error:
        assert str(error) == "MANAGER_CLOSE_CAPTURE_MODE_INVALID"
    else:
        raise AssertionError("unexpected manager close mode must fail closed")
    assert calls == []
