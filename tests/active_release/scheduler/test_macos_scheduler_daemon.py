from __future__ import annotations

import json
import os
import signal
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pytest

from ops import run_v35_macos_scheduler_daemon as daemon
from ops.install_v35_macos_launchagents import build_scheduler_plist


SHANGHAI = ZoneInfo("Asia/Shanghai")
RELEASE_ID = "20260827T060000Z-v35-main-scheduler-daemon"


def _result(*, status: str = "NO_DUE_SLOT", release_id: str = RELEASE_ID) -> str:
    return json.dumps(
        {
            "schema_version": "v3_5.macos_scheduler_result.v1",
            "status": status,
            "release_id": release_id,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        sort_keys=True,
    )


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _MinuteEvent:
    def __init__(self, clock: _Clock, *, stop_after_waits: int) -> None:
        self.clock = clock
        self.stop_after_waits = stop_after_waits
        self.waits = 0
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def set(self) -> None:
        self._stopped = True

    def wait(self, _timeout: float | None = None) -> bool:
        self.waits += 1
        if self.waits >= self.stop_after_waits:
            self.clock.value += timedelta(minutes=1)
            self._stopped = True
        elif self.waits == 1:
            # The first wake stays in the same Shanghai minute.  A daemon
            # must not call the one-shot a second time for that minute.
            self.clock.value += timedelta(seconds=10)
        else:
            self.clock.value += timedelta(minutes=1)
        return self._stopped


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_main: Callable[[list[str]], int],
    clock: _Clock,
    event: _MinuteEvent,
    **kwargs: Any,
) -> tuple[int, str]:
    monkeypatch.setenv("V35_RELEASE_ID", RELEASE_ID)
    monkeypatch.setenv("PRODUCTION_ALLOWED", "false")
    monkeypatch.setenv("BUY_GATE_UPDATED", "false")
    monkeypatch.setenv("ORDERS_SENT", "false")
    result = daemon.run_daemon(
        ["--release-id", RELEASE_ID],
        scheduler_main=fake_main,
        clock=clock,
        stop_event=event,
        install_signals=False,
        poll_interval_seconds=0.001,
        **kwargs,
    )
    return result, daemon.last_emitted_output()


def test_daemon_deduplicates_same_minute_and_runs_once_per_new_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 8, 27, 9, 0, 5, tzinfo=SHANGHAI))
    event = _MinuteEvent(clock, stop_after_waits=3)
    calls: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        calls.append(list(argv))
        print(_result())
        return 0

    result, output = _run(monkeypatch, fake_main=fake_main, clock=clock, event=event)

    assert result == 0
    assert len(calls) == 2
    assert len({"09:00", "09:01"}) == 2
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    cycles = [item for item in records if item.get("status") == "DAEMON_CYCLE"]
    assert [item["minute"] for item in cycles] == ["2026-08-27T09:00", "2026-08-27T09:01"]
    assert len({item["pid"] for item in cycles}) == 1
    assert sum(item.get("status") == "DAEMON_CYCLE" for item in records) == 2


def test_no_due_cycle_does_not_call_business_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(datetime(2026, 8, 27, 2, 0, 5, tzinfo=SHANGHAI))
    event = _MinuteEvent(clock, stop_after_waits=2)
    business_calls: list[str] = []

    def fake_main(argv: list[str]) -> int:
        business_calls.append("scheduler-dispatch")
        print(_result(status="NO_DUE_SLOT"))
        return 0

    result, output = _run(monkeypatch, fake_main=fake_main, clock=clock, event=event)

    assert result == 0
    assert len(business_calls) == 1
    assert '"result_status": "NO_DUE_SLOT"' in output
    assert '"business_writes": 0' not in output  # the daemon does not invent a counter


def test_cycle_exception_isolated_and_next_minute_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 8, 27, 9, 0, 5, tzinfo=SHANGHAI))
    event = _MinuteEvent(clock, stop_after_waits=3)
    calls = 0

    def fake_main(argv: list[str]) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary cycle failure")
        print(_result())
        return 0

    result, output = _run(monkeypatch, fake_main=fake_main, clock=clock, event=event)

    assert result == 0
    assert calls == 2
    assert "DAEMON_CYCLE_FAILED" in output
    assert '"result_status": "NO_DUE_SLOT"' in output


def test_safety_or_identity_violation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(datetime(2026, 8, 27, 2, 0, 5, tzinfo=SHANGHAI))
    event = _MinuteEvent(clock, stop_after_waits=2)
    calls = 0

    def fake_main(argv: list[str]) -> int:
        nonlocal calls
        calls += 1
        print(_result(release_id="wrong-release"))
        return 0

    result, output = _run(monkeypatch, fake_main=fake_main, clock=clock, event=event)

    assert result != 0
    assert calls == 1
    assert "DAEMON_FATAL" in output


def test_sigterm_sets_stop_and_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(datetime(2026, 8, 27, 2, 0, 5, tzinfo=SHANGHAI))
    event = daemon.threading.Event()
    original_term = signal.getsignal(signal.SIGTERM)
    original_int = signal.getsignal(signal.SIGINT)
    finished: list[int] = []

    def fake_main(argv: list[str]) -> int:
        print(_result())
        return 0

    def stop_process() -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(0.03, stop_process)
    timer.start()
    try:
        finished.append(
            daemon.run_daemon(
                ["--release-id", RELEASE_ID],
                scheduler_main=fake_main,
                clock=clock,
                stop_event=event,
                install_signals=True,
                poll_interval_seconds=0.001,
            )
        )
    finally:
        timer.cancel()
        signal.signal(signal.SIGTERM, original_term)
        signal.signal(signal.SIGINT, original_int)

    assert finished == [0]
    assert event.is_set()
    assert "DAEMON_STOPPED" in daemon.last_emitted_output()


def _plist_kwargs() -> dict[str, str]:
    root = "/Users/lexi/Library/Application Support/com.lexi.v35.local"
    return {
        "launch_script": f"{root}/releases/{RELEASE_ID}/app/ops/launch_v35_macos_scheduler.sh",
        "app_root": f"{root}/releases/{RELEASE_ID}/app",
        "runtime_root": f"{root}/releases/{RELEASE_ID}/runtime",
        "data_root": f"{root}/state/data",
        "ledger_root": f"{root}/state/dispatcher",
        "stage_selection_root": "/Users/lexi/Library/Application Support/com.lexi.stage-center.local/state/selection",
        "preselection_input_root": f"{root}/state/data/preselection_inputs",
        "shared_data_root": f"{root}/state/workspace/v3_shared_data/.runtime/data",
        "hk_universe_root": f"{root}/state/workspace/v3_shared_data",
        "shared_package_root": f"{root}/releases/{RELEASE_ID}/app/upstreams/v3_shared_data",
        "selector_data_root": f"{root}/state/workspace/数据",
        "hk_0_2_python": f"{root}/releases/{RELEASE_ID}/app/ops/launch_hk_0_2_python_nosite.sh",
        "research_panel_receipt_root": f"{root}/state/research_panel_daily/receipts",
        "selector_pointer": f"{root}/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        "backtest_pointer": f"{root}/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        "review_core_package_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/app",
        "review_core_shared_package_root": f"{root}/releases/{RELEASE_ID}/app/upstreams/v3_shared_data",
        "review_core_shared_store_root": f"{root}/state/workspace/v3_shared_data/.runtime/data",
        "review_core_runtime_root": f"{root}/releases/{RELEASE_ID}/runtime",
        "review_core_calendar_path": f"{root}/releases/{RELEASE_ID}/app/contracts/trading_calendar_2026.json",
        "review_core_hk_root": f"{root}/state/workspace/v3_shared_data",
        "review_core_close_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/close_reviews",
        "review_core_fupan_store_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/fupan_pools",
        "review_core_stage7_store_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/stage7_pools",
        "review_core_bundle_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/review_bundle",
        "research_panel_a_tdx_root": f"{root}/state/research_panel_daily/tdx",
        "research_panel_hk_tdx_root": f"{root}/state/research_panel_daily/hk_tdx",
        "research_panel_a_sync_script": f"{root}/releases/{RELEASE_ID}/app/runtime/v1/tdxpy_daily_vipdoc_sync_v1.py",
        "research_panel_a_formula_script": f"{root}/releases/{RELEASE_ID}/app/runtime/v1/data_layer_daily_formula_increment_update_v1.py",
        "research_panel_a_seed_panel": f"{root}/state/workspace/数据/selector_ready_panels/seed.parquet",
        "research_panel_a_data_root": f"{root}/state/workspace/数据",
        "research_panel_a_selector_pointer": f"{root}/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        "research_panel_a_backtest_pointer": f"{root}/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        "research_panel_a_selector_seed": f"{root}/state/workspace/数据/selector_ready_panels/seed.parquet",
        "research_panel_a_backtest_seed": f"{root}/state/workspace/数据/backtest_panels/seed.parquet",
        "research_panel_a_contract_csv": f"{root}/releases/{RELEASE_ID}/app/runtime/v1/authoritative_field_contract_v0.csv",
        "research_panel_a_canonical_formula": f"{root}/releases/{RELEASE_ID}/app/runtime/v1/build_canonical_formula_research_panel.py",
        "research_panel_a_return_root": f"{root}/state/research_panel_daily/a_formula_runs",
        "research_panel_hk_updater_script": f"{root}/releases/{RELEASE_ID}/app/upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py",
        "research_panel_hk_python_executable": f"{root}/releases/{RELEASE_ID}/runtime/venvs/v3.5-hk02/bin/python",
        "research_panel_hk_asset_root": f"{root}/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2",
    }


def test_daemon_plist_has_single_persistent_launch_schedule() -> None:
    payload = build_scheduler_plist(
        **_plist_kwargs(),
        release_id=RELEASE_ID,
        upstream_fingerprint="upstream-sha256",
        persistent_daemon=True,
    )

    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["ThrottleInterval"] == 60
    assert "StartCalendarInterval" not in payload
    assert "StartInterval" not in payload
    assert "ProcessType" not in payload
    assert payload["EnvironmentVariables"]["V35_RELEASE_ID"] == RELEASE_ID
    assert payload["EnvironmentVariables"]["V35_DAEMON_MODE"] == "persistent-minute"
    assert payload["EnvironmentVariables"]["V35_DAEMON_HEARTBEAT_SECONDS"] == "60"


def test_persistent_daemon_plist_binds_external_scheduler_logs() -> None:
    payload = build_scheduler_plist(
        **_plist_kwargs(),
        release_id=RELEASE_ID,
        upstream_fingerprint="upstream-sha256",
        persistent_daemon=True,
    )

    root = "/Users/lexi/Library/Application Support/com.lexi.v35.local"
    assert payload["StandardOutPath"] == (
        f"{root}/state/logs/v35-a3-v4-scheduler.stdout.log"
    )
    assert payload["StandardErrorPath"] == (
        f"{root}/state/logs/v35-a3-v4-scheduler.stderr.log"
    )


def test_main_keeps_one_shot_scheduler_arguments_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run_daemon(argv: list[str], **kwargs: Any) -> int:
        observed["argv"] = argv
        observed.update(kwargs)
        return 0

    monkeypatch.setattr(daemon, "run_daemon", fake_run_daemon)
    result = daemon.main(
        [
            "--poll-interval-seconds",
            "2",
            "--heartbeat-seconds",
            "60",
            "--data-root",
            "/tmp/data",
            "--ledger-root",
            "/tmp/ledger",
            "--release-id",
            RELEASE_ID,
        ]
    )

    assert result == 0
    assert observed["argv"] == [
        "--data-root",
        "/tmp/data",
        "--ledger-root",
        "/tmp/ledger",
        "--release-id",
        RELEASE_ID,
    ]
    assert observed["poll_interval_seconds"] == 2
    assert observed["heartbeat_seconds"] == 60


def test_daemon_does_not_copy_business_scheduler_algorithm() -> None:
    source = Path(daemon.__file__).read_text(encoding="utf-8")
    assert "run_v35_macos_scheduler" in source
    assert "resolve_due_slot" not in source
    assert "run_scheduled_slot" not in source
    assert "ALL_SLOTS" not in source


def test_scheduler_launcher_selects_persistent_entry_only_for_t060_mode() -> None:
    source = (
        Path(daemon.__file__).parents[0] / "launch_v35_macos_scheduler.sh"
    ).read_text(encoding="utf-8")
    assert 'V35_DAEMON_MODE:-' in source
    assert '"persistent-minute"' in source
    assert 'ops.run_v35_macos_scheduler_daemon' in source
