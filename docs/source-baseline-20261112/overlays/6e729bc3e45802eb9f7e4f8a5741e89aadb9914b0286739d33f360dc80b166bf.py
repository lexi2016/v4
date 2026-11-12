from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts.live_acquisition.pytdx_exhq import collect_pytdx_exhq_minute
from scripts.live_acquisition.pytdx_exhq_probe import MARKER as EXHQ_MARKER
from scripts.live_acquisition.pytdx_hq import collect_pytdx_hq_minute


TRADE_DATE = "20260817"
STAGE_ID = "STAGE_0930_0935"
HQ_MARKER = "__PYTDX_HQ_MINUTE_JSON__"


def _python_path(tmp_path: Path) -> Path:
    path = tmp_path / "python"
    path.write_text("", encoding="utf-8")
    return path


def _raw_bar(code: str) -> dict[str, object]:
    return {
        "time_key": "2026-08-17 09:31:00",
        "code": code,
        "name": code,
        "open": 10.0,
        "high": 10.2,
        "low": 9.9,
        "close": 10.1,
        "volume": 100.0,
        "turnover": 1000.0,
        "last_close": 9.9,
    }


def _runner_factory(marker: str, calls: list[dict[str, object]], *, fail_indexes: set[int] | None = None):
    failures = fail_indexes or set()

    def runner(argv, *, input, timeout, **kwargs):
        request = json.loads(input)
        calls.append({"argv": argv, "request": request, "timeout": timeout, "kwargs": kwargs})
        index = len(calls) - 1
        if index in failures:
            raise subprocess.TimeoutExpired(argv, timeout)
        codes = request["codes"]
        payload = {
            "raw_rows": [_raw_bar(code) for code in codes],
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": len(codes),
            "completed_code_count": len(codes),
            "source_host": f"test:{index}",
        }
        return SimpleNamespace(
            returncode=0,
            stdout=marker + json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    return runner


def test_hq_batches_preserve_order_and_sum_coverage(tmp_path: Path) -> None:
    codes = [f"SZ.{index:06d}" for index in range(1, 66)]
    calls: list[dict[str, object]] = []
    result = collect_pytdx_hq_minute(
        _python_path(tmp_path),
        TRADE_DATE,
        STAGE_ID,
        codes,
        process_runner=_runner_factory(HQ_MARKER, calls),
    )

    assert [len(call["request"]["codes"]) for call in calls] == [32, 32, 1]
    assert result.status == "READ_OK"
    assert result.requested_code_count == 65
    assert result.completed_code_count == 65
    assert [row["code"] for row in result.rows] == codes
    assert len({row["code"] for row in result.rows}) == 65
    assert all(call["request"]["trade_date"] == TRADE_DATE for call in calls)
    assert all(call["request"]["stage_id"] == STAGE_ID for call in calls)
    assert all(call["timeout"] <= 180 for call in calls)


def test_hq_timeout_chunk_keeps_successful_chunk_rows(tmp_path: Path) -> None:
    codes = [f"SZ.{index:06d}" for index in range(1, 65)]
    calls: list[dict[str, object]] = []
    result = collect_pytdx_hq_minute(
        _python_path(tmp_path),
        TRADE_DATE,
        STAGE_ID,
        codes,
        process_runner=_runner_factory(HQ_MARKER, calls, fail_indexes={0}),
    )

    assert len(calls) == 2
    assert result.status == "DATA_PARTIAL"
    assert result.requested_code_count == 64
    assert result.completed_code_count == 32
    assert [row["code"] for row in result.rows] == codes[32:]
    assert "timeout" in result.error.lower()
    assert result.cannot_confirm


def test_hq_all_failed_chunks_fail_closed_without_rows(tmp_path: Path) -> None:
    codes = [f"SZ.{index:06d}" for index in range(1, 65)]
    calls: list[dict[str, object]] = []
    result = collect_pytdx_hq_minute(
        _python_path(tmp_path),
        TRADE_DATE,
        STAGE_ID,
        codes,
        process_runner=_runner_factory(HQ_MARKER, calls, fail_indexes={0, 1}),
    )

    assert len(calls) == 2
    assert result.status == "READ_FAILED"
    assert result.rows == []
    assert result.requested_code_count == 64
    assert result.completed_code_count == 0
    assert result.cannot_confirm


def test_exhq_batches_preserve_order_and_exact_window(tmp_path: Path) -> None:
    codes = [f"HK.{index:05d}" for index in range(1, 66)]
    calls: list[dict[str, object]] = []
    result = collect_pytdx_exhq_minute(
        _python_path(tmp_path),
        TRADE_DATE,
        STAGE_ID,
        codes,
        process_runner=_runner_factory(EXHQ_MARKER, calls),
    )

    assert [len(call["request"]["codes"]) for call in calls] == [64, 1]
    assert result.status == "READ_OK"
    assert result.requested_code_count == 65
    assert result.completed_code_count == 65
    assert [row["code"] for row in result.rows] == codes
    assert len({row["code"] for row in result.rows}) == 65
    assert all(call["request"]["trade_date"] == TRADE_DATE for call in calls)
    assert all(call["request"]["stage_id"] == STAGE_ID for call in calls)
    assert all(call["timeout"] <= 180 for call in calls)


def test_exhq_timeout_chunk_keeps_successful_rows_and_errors(tmp_path: Path) -> None:
    codes = [f"HK.{index:05d}" for index in range(1, 66)]
    calls: list[dict[str, object]] = []
    result = collect_pytdx_exhq_minute(
        _python_path(tmp_path),
        TRADE_DATE,
        STAGE_ID,
        codes,
        process_runner=_runner_factory(EXHQ_MARKER, calls, fail_indexes={0}),
    )

    assert len(calls) == 2
    assert result.status == "DATA_PARTIAL"
    assert result.requested_code_count == 65
    assert result.completed_code_count == 1
    assert [row["code"] for row in result.rows] == codes[-1:]
    assert "timeout" in result.error.lower()
    assert result.cannot_confirm
