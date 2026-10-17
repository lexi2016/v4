from __future__ import annotations

import importlib
import json
from datetime import datetime as RealDateTime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


runner = importlib.import_module("ops.run_us_market_slot")
SHANGHAI = ZoneInfo("Asia/Shanghai")

# These are the two observed launch times from the daily job stdout: the
# unmodified CLI converted them to 2102/2213 and failed before owner dispatch.
OBSERVED_DELAYED_LAUNCHES = (
    ("2026-10-05T21:02:00+08:00", "2100"),
    ("2026-10-05T22:13:00+08:00", "2200"),
)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, captured_at: str) -> None:
    frozen = RealDateTime.fromisoformat(captured_at).astimezone(SHANGHAI)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr(runner, "datetime", FrozenDateTime)


def _capture_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def capture(**kwargs):
        calls.append(kwargs)
        return {"status": "DRY_RUN_SELECTED"}

    monkeypatch.setattr(runner, "run_us_market_slot", capture)
    return calls


def _invoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    captured_at: str,
    *,
    explicit_slot: str | None = None,
) -> tuple[int, dict, str, str]:
    _freeze_clock(monkeypatch, captured_at)
    command = [
        "--data-root", str(tmp_path / "data"),
        "--ledger-root", str(tmp_path / "ledger"),
        "--dry-run",
    ]
    if explicit_slot is not None:
        command.extend(("--slot", explicit_slot))
    status = runner.main(command)
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    return status, payload, captured.out, captured.err


@pytest.mark.parametrize(("captured_at", "expected_slot"), OBSERVED_DELAYED_LAUNCHES)
def test_actual_delayed_launch_inputs_map_to_the_latest_planned_slot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    captured_at: str,
    expected_slot: str,
) -> None:
    calls = _capture_dispatch(monkeypatch)
    status, payload, _, stderr = _invoke_main(monkeypatch, capsys, tmp_path, captured_at)

    assert status == 0, stderr
    assert payload["status"] == "DRY_RUN_SELECTED"
    assert calls[0]["slot"] == expected_slot
    assert calls[0]["business_date"] == "20261005"
    # Slot attribution changes; the runner still passes no fabricated capture
    # timestamp or scheduled-time override into the existing dispatcher.
    assert "captured_at" not in calls[0]


@pytest.mark.parametrize(
    ("captured_at", "expected_slot"),
    (
        ("2026-10-06T04:15:00+08:00", "0415"),
        ("2026-10-06T04:30:00+08:00", "0415"),
        ("2026-10-06T05:15:00+08:00", "0515"),
        ("2026-10-06T05:30:00+08:00", "0515"),
        ("2026-10-06T21:00:00+08:00", "2100"),
        ("2026-10-06T21:15:00+08:00", "2100"),
        ("2026-10-06T22:00:00+08:00", "2200"),
        ("2026-10-06T22:15:00+08:00", "2200"),
    ),
)
def test_default_schedule_slot_accepts_on_time_and_exact_15_minute_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    captured_at: str,
    expected_slot: str,
) -> None:
    calls = _capture_dispatch(monkeypatch)
    status, payload, _, stderr = _invoke_main(monkeypatch, capsys, tmp_path, captured_at)

    assert status == 0, stderr
    assert payload["status"] == "DRY_RUN_SELECTED"
    assert calls[0]["slot"] == expected_slot


@pytest.mark.parametrize(
    ("captured_at", "reason"),
    (
        ("2026-10-06T21:16:00+08:00", "US_DEFAULT_SLOT_WINDOW_EXPIRED"),
        ("2026-10-06T22:16:00+08:00", "US_DEFAULT_SLOT_WINDOW_EXPIRED"),
        ("2026-10-07T00:05:00+08:00", "US_DEFAULT_SLOT_NOT_DUE"),
    ),
)
def test_default_slot_fails_closed_after_grace_and_at_cross_day_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    captured_at: str,
    reason: str,
) -> None:
    calls = _capture_dispatch(monkeypatch)
    status, payload, _, stderr = _invoke_main(monkeypatch, capsys, tmp_path, captured_at)

    assert status == 1
    assert payload["status"] == "FAILED"
    assert reason in payload["reason"]
    assert calls == []
    assert stderr


def test_explicit_slot_remains_strict_and_is_never_remapped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls = _capture_dispatch(monkeypatch)
    status, payload, _, stderr = _invoke_main(
        monkeypatch, capsys, tmp_path, "2026-10-06T21:16:00+08:00", explicit_slot="0415"
    )

    assert status == 0, stderr
    assert calls[0]["slot"] == "0415"


def test_us_close_slot_keeps_hk_target_distinct_and_skips_holiday() -> None:
    request = runner._request_for_slot(
        business_date="20261017",
        slot="0415",
    )

    assert request.scheduled_date == "20261017"
    assert request.business_date == "20261017"
    assert request.target_date == "20261020"


def test_explicit_non_contract_slot_still_fails_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _freeze_clock(monkeypatch, "2026-10-06T21:02:00+08:00")
    status, payload, _, stderr = _invoke_main(
        monkeypatch, capsys, tmp_path, "2026-10-06T21:02:00+08:00", explicit_slot="2102"
    )

    assert status == 1
    assert payload["status"] == "FAILED"
    assert payload["slot"] == "2102"
    assert "US_SLOT_NOT_ALLOWED" in payload["reason"]
    assert "US_SLOT_NOT_ALLOWED" in stderr
