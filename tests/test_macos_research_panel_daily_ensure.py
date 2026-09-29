from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ops import macos_research_panel_daily as panel


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_after_1700_ensure_skips_when_selector_pointer_is_exact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_args: True)

    def fail_runner(_date: str):
        raise AssertionError("exact selector pointer must prevent repeated lane execution")

    result = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 18, 0, tzinfo=SHANGHAI),
        a_runner=fail_runner,
        hk_runner=fail_runner,
    )

    assert result["status"] == "ALREADY_READY"
    assert result["idempotent"] is True
    assert result["runner_called"] is False


def test_after_1700_ensure_retries_failed_attempt_with_backoff_and_caps_retries(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_args: False)
    calls: list[tuple[str, str]] = []
    outcomes = iter(("FAILED", "READY", "READY", "READY"))

    def a_runner(date: str):
        calls.append(("A", date))
        status = next(outcomes)
        return {"status": status, "target_date": date, "row_count": 1}

    def hk_runner(date: str):
        calls.append(("HK", date))
        return {"status": "READY", "target_date": date, "row_count": 1}

    first = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 18, 0, tzinfo=SHANGHAI),
        a_runner=a_runner,
        hk_runner=hk_runner,
    )
    backoff = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 18, 2, 30, tzinfo=SHANGHAI),
        a_runner=a_runner,
        hk_runner=hk_runner,
    )
    second = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 18, 6, tzinfo=SHANGHAI),
        a_runner=a_runner,
        hk_runner=hk_runner,
    )

    assert first["status"] == "ATTEMPTED"
    assert first["runner_called"] is True
    assert backoff["status"] == "RETRY_BACKOFF"
    assert backoff["runner_called"] is False
    assert second["status"] == "ATTEMPTED"
    assert second["runner_called"] is True
    assert calls == [("A", "20260817"), ("HK", "20260817"), ("A", "20260817"), ("HK", "20260817")]


def test_after_1700_ensure_ready_attempt_retries_when_selector_pointer_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_args: False)
    calls: list[str] = []

    def ready_runner(date: str):
        calls.append(date)
        return {"status": "READY", "target_date": date, "row_count": 1}

    first = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 18, 0, tzinfo=SHANGHAI),
        a_runner=ready_runner,
        hk_runner=ready_runner,
    )
    second = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 23, 30, tzinfo=SHANGHAI),
        a_runner=ready_runner,
        hk_runner=ready_runner,
    )
    assert first["overall_status"] == "READY"
    assert second["status"] == "ATTEMPTED"
    assert second["runner_called"] is True
    assert second["selector_pointer_ready"] is False
    assert len(calls) == 4


def test_before_1700_ensure_is_a_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_args: False)
    result = panel.ensure_after_1700(
        target_date="20260817",
        receipt_root=tmp_path,
        selector_pointer=tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt",
        now=datetime(2026, 8, 17, 16, 59, tzinfo=SHANGHAI),
        a_runner=lambda _date: {"status": "READY"},
        hk_runner=lambda _date: {"status": "READY"},
    )
    assert result["status"] == "BEFORE_1700"
    assert result["runner_called"] is False
