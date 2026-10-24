from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pytest


def _bar(date_value: int, close: float) -> dict[str, object]:
    return {
        "year": date_value // 10000,
        "month": date_value // 100 % 100,
        "day": date_value % 100,
        "open": close - 0.2,
        "high": close + 0.2,
        "low": close - 0.4,
        "close": close,
        "amount": 1000.0,
        "vol": 100.0,
    }


def _write_day(path: Path, bars: list[dict[str, object]]) -> None:
    from ops.a_share_daily_sync import pack_hq_bar

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(pack_hq_bar(bar) for bar in bars))


class _FakeSession:
    def __init__(self, host: str, scripts: dict[tuple[str, str], list[list[dict[str, object]]]], calls: list[tuple[str, str]]) -> None:
        self.host = host
        self.scripts = scripts
        self.calls = calls

    def connect(self, host: str, port: int, time_out: float | None = None) -> bool:
        assert host == self.host
        return True

    def get_security_bars(self, _kline: int, _market: int, code: str, _start: int, _count: int):
        self.calls.append((self.host, code))
        queue = self.scripts.setdefault((self.host, code), [])
        return queue.pop(0) if queue else []

    def disconnect(self) -> None:
        return None


def test_sync_reconnects_and_retries_only_the_bad_symbol(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    targets = [
        DailyTarget(code=code, market=0, path=tmp_path / f"{code}.day")
        for code in ("000001", "000002", "000003")
    ]
    for index, target in enumerate(targets, start=1):
        _write_day(target.path, [_bar(20260818, 9.0 + index)])
    scripts = {
        ("h1", "000001"): [[_bar(20260819, 11.0)]],
        ("h1", "000002"): [[]],
        ("h2", "000003"): [[_bar(20260819, 13.0)]],
        ("h2", "000002"): [[_bar(20260819, 12.0)]],
    }
    calls: list[tuple[str, str]] = []

    def factory(host: str, _port: int):
        return _FakeSession(host, scripts, calls)

    result = run_sync(
        targets,
        target_date="20260819",
        api_factory=factory,
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert calls == [
        ("h1", "000001"),
        ("h1", "000002"),
        ("h2", "000002"),
        ("h2", "000003"),
    ]
    assert all(result["by_symbol"][code]["target_date_ready"] for code in ("000001", "000002", "000003"))


def test_increment_appends_each_missing_day_through_target_without_future(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, pack_hq_bar, read_hq_day_bars, run_sync

    target = DailyTarget(code="000004", market=0, path=tmp_path / "000004.day")
    prefix = [_bar(20260909, 10.0)]
    _write_day(target.path, prefix)
    scripts = {
        ("h1", "000004"): [[
            _bar(20260909, 10.0),
            _bar(20260910, 10.5),
            _bar(20260911, 11.0),
        ]]
    }

    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda host, _port: _FakeSession(host, scripts, []),
        host_candidates=(("h1", 7709),),
    )

    assert result["status"] == "PASS"
    assert result["by_symbol"]["000004"]["records_written"] == 2
    assert [
        row["year"] * 10000 + row["month"] * 100 + row["day"]
        for row in read_hq_day_bars(target.path)
    ] == [20260909, 20260910, 20260911]
    assert target.path.read_bytes().startswith(b"".join(pack_hq_bar(row) for row in prefix))


def test_current_target_is_not_requested_again(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000005", market=0, path=tmp_path / "000005.day")
    _write_day(target.path, [_bar(20260911, 11.0)])
    original = target.path.read_bytes()
    calls: list[tuple[str, str]] = []

    def factory(_host: str, _port: int):
        raise AssertionError("current target must not open a provider session")

    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=factory,
        host_candidates=(("h1", 7709),),
    )

    assert result["status"] == "PASS"
    assert result["by_symbol"]["000005"]["status"] == "ALREADY_CURRENT"
    assert result["updated_count"] == 0
    assert calls == []
    assert target.path.read_bytes() == original


def test_malformed_existing_current_history_is_rejected_before_provider(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000019", market=0, path=tmp_path / "000019.day")
    malformed_current = _bar(20260911, 11.0)
    malformed_current["high"] = 10.0
    malformed_current["low"] = 9.0
    _write_day(target.path, [_bar(20260910, 10.0), malformed_current])
    original = target.path.read_bytes()
    provider_calls: list[tuple[object, ...]] = []

    def factory(*args: object):
        provider_calls.append(args)
        raise AssertionError("malformed local history must fail before provider")

    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=factory,
        host_candidates=(("h1", 7709),),
        dry_run=True,
        progress_path=tmp_path / "progress.json",
    )

    row = result["by_symbol"]["000019"]
    assert result["status"] == "FAILED"
    assert row["status"] == "FAILED"
    assert row["classification"] == "QUARANTINED"
    assert row["reason_code"] == "INVALID_BAR"
    assert row["failure_type"] == "invalid_bar:source_close_outside_high_low"
    assert provider_calls == []
    assert target.path.read_bytes() == original


def test_future_response_is_rejected_without_writing(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000007", market=0, path=tmp_path / "000007.day")
    _write_day(target.path, [_bar(20260909, 10.0)])
    original = target.path.read_bytes()
    scripts = {
        ("h1", "000007"): [[
            _bar(20260910, 10.5),
            _bar(20260911, 11.0),
            _bar(20260912, 11.5),
        ]]
    }

    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda host, _port: _FakeSession(host, scripts, []),
        host_candidates=(("h1", 7709),),
    )

    assert result["status"] == "FAILED"
    assert len(result["failures"]) == 1
    assert {
        key: result["failures"][0][key]
        for key in ("symbol", "host", "failure_type")
    } == {
        "symbol": "000007",
        "host": "h1:7709",
        "failure_type": "out_of_scope_after_target_date",
    }
    assert result["failures"][0]["reason_code"] == "OUT_OF_SCOPE_AFTER_TARGET_DATE"
    assert target.path.read_bytes() == original


def test_run_budget_exhaustion_is_cannot_confirm_and_does_not_write(tmp_path: Path) -> None:
    import time

    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000006", market=0, path=tmp_path / "000006.day")
    _write_day(target.path, [_bar(20260909, 10.0)])
    original = target.path.read_bytes()

    class _SlowSession:
        def connect(self, _host: str, _port: int, time_out: float | None = None) -> bool:
            del time_out
            return True

        def get_security_bars(self, *_args: object):
            time.sleep(0.02)
            return [_bar(20260911, 11.0)]

        def disconnect(self) -> None:
            return None

    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda _host, _port: _SlowSession(),
        host_candidates=(("h1", 7709),),
        run_budget_seconds=0.005,
    )

    assert result["status"] == "TIMEOUT"
    assert result["exit_code"] == 124
    assert result["timeout"] is True
    assert result["budgets"]["run_budget_seconds"] == 0.005
    assert result["by_symbol"]["000006"]["status"] == "CANNOT_CONFIRM"
    assert result["by_symbol"]["000006"]["target_date_ready"] is False
    assert result["failures"][0]["failure_type"].startswith("A_SYNC_TIMEOUT:RUN")
    assert target.path.read_bytes() == original


def test_all_hosts_empty_quarantines_and_resets_host_cursor(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    targets = [
        DailyTarget(code=code, market=0, path=tmp_path / f"{code}.day")
        for code in ("000002", "000003")
    ]
    for target in targets:
        _write_day(target.path, [_bar(20260818, 10.0)])
    original = targets[0].path.read_bytes()
    scripts = {
        ("h1", "000002"): [[]],
        ("h2", "000002"): [[]],
        ("h1", "000003"): [[_bar(20260819, 12.0)]],
    }
    calls: list[tuple[str, str]] = []

    result = run_sync(
        targets,
        target_date="20260819",
        api_factory=lambda host, _port: _FakeSession(host, scripts, calls),
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "FAILED"
    assert result["by_symbol"]["000002"]["failure_type"] == "empty_response"
    assert calls == [
        ("h1", "000002"),
        ("h2", "000002"),
        ("h1", "000003"),
    ]
    assert targets[0].path.read_bytes() == original
    assert result["by_symbol"]["000003"]["status"] == "UPDATED"


def test_sdk_factories_enable_strict_parser_errors(monkeypatch) -> None:
    import ops.a_share_daily_sync as sync

    constructor_kwargs: list[dict[str, object]] = []

    class _StrictFactorySession:
        def __init__(self, **kwargs: object) -> None:
            constructor_kwargs.append(kwargs)

        def connect(self, _host: str, _port: int, time_out: float | None = None) -> bool:
            del time_out
            return True

        def get_security_bars(self, *_args: object):
            return [_bar(20260819, 10.0)]

        def disconnect(self) -> None:
            return None

    monkeypatch.setattr(sync, "TdxHq_API", _StrictFactorySession)
    monkeypatch.setattr(sync, "hq_hosts", [("h1", "h1", 7709)])

    sync._runtime_api_factory("h1", 7709)
    sync.connect_hq(None, 1.5)

    assert constructor_kwargs == [
        {"auto_retry": False, "raise_exception": True},
        {"auto_retry": False, "raise_exception": True},
    ]


def test_sdk_parse_exception_rotates_to_host_with_valid_bars(tmp_path: Path) -> None:
    import struct

    from pytdx.errors import TdxFunctionCallError
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000002", market=0, path=tmp_path / "000002.day")
    _write_day(target.path, [_bar(20260818, 10.0)])
    calls: list[tuple[str, str]] = []

    def factory(host: str, _port: int):
        class _ProtocolSession:
            def connect(self, _host: str, _port: int, time_out: float | None = None) -> bool:
                del time_out
                return True

            def get_security_bars(self, *_args: object):
                calls.append((host, target.code))
                if host == "h1":
                    error = TdxFunctionCallError("calling function error")
                    error.original_exception = struct.error(
                        "unpack requires a buffer of 4 bytes"
                    )
                    raise error
                return [_bar(20260819, 10.4)]

            def disconnect(self) -> None:
                return None

        return _ProtocolSession()

    result = run_sync(
        [target],
        target_date="20260819",
        api_factory=factory,
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "PASS"
    assert result["by_symbol"]["000002"]["status"] == "UPDATED"
    assert calls == [("h1", "000002"), ("h2", "000002")]


def test_sdk_parse_exception_is_quarantined_with_original_chain(tmp_path: Path) -> None:
    import struct

    from pytdx.errors import TdxFunctionCallError
    from ops.a_share_daily_sync import (
        DailyTarget,
        PROTOCOL_RESPONSE_MALFORMED,
        run_sync,
    )

    target = DailyTarget(code="000003", market=0, path=tmp_path / "000003.day")
    _write_day(target.path, [_bar(20260818, 10.0)])
    calls: list[tuple[str, str]] = []

    def factory(host: str, _port: int):
        class _ProtocolSession:
            def connect(self, _host: str, _port: int, time_out: float | None = None) -> bool:
                del time_out
                return True

            def get_security_bars(self, *_args: object):
                calls.append((host, target.code))
                error = TdxFunctionCallError("calling function error")
                error.original_exception = struct.error(
                    "unpack requires a buffer of 4 bytes"
                )
                raise error

            def disconnect(self) -> None:
                return None

        return _ProtocolSession()

    result = run_sync(
        [target],
        target_date="20260819",
        api_factory=factory,
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    row = result["by_symbol"]["000003"]
    assert result["status"] == "FAILED"
    assert result["exit_code"] == 2
    assert row["failure_type"] == PROTOCOL_RESPONSE_MALFORMED
    assert row["original_exception_type"] == "error"
    assert row["original_exception_module"] == "struct"
    assert [item["type"] for item in row["exception_chain"]] == [
        "pytdx.errors.TdxFunctionCallError",
        "struct.error",
    ]
    assert "empty_response" not in repr(row).lower()
    assert calls == [("h1", "000003"), ("h2", "000003")]


def test_second_failure_keeps_original_file_and_is_nonzero(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000002", market=0, path=tmp_path / "000002.day")
    _write_day(target.path, [_bar(20260818, 10.0)])
    original = target.path.read_bytes()
    scripts = {
        ("h1", "000002"): [[]],
        ("h2", "000002"): [[_bar(20260818, 100.0)]],
    }
    calls: list[tuple[str, str]] = []

    result = run_sync(
        [target],
        target_date="20260819",
        api_factory=lambda host, _port: _FakeSession(host, scripts, calls),
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "FAILED"
    assert result["exit_code"] != 0
    assert target.path.read_bytes() == original
    assert len(result["failures"]) == 1
    assert {
        key: result["failures"][0][key]
        for key in ("symbol", "host", "failure_type")
    } == {
        "symbol": "000002",
        "host": "h2:7709",
        "failure_type": "target_date_missing",
    }
    assert result["failures"][0]["reason_code"] == "TARGET_DATE_MISSING"


def test_failed_symbol_does_not_exhaust_hosts_for_next_symbol(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    targets = [
        DailyTarget(code=code, market=0, path=tmp_path / f"{code}.day")
        for code in ("000001", "000002", "000003")
    ]
    for index, target in enumerate(targets, start=1):
        _write_day(target.path, [_bar(20260818, 9.0 + index)])
    symbol2_original = targets[1].path.read_bytes()
    scripts = {
        ("h1", "000001"): [[_bar(20260819, 11.0)]],
        ("h1", "000002"): [[]],
        ("h2", "000002"): [[_bar(20260818, 100.0)]],
        ("h1", "000003"): [[_bar(20260819, 13.0)]],
    }
    calls: list[tuple[str, str]] = []

    result = run_sync(
        targets,
        target_date="20260819",
        api_factory=lambda host, _port: _FakeSession(host, scripts, calls),
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "FAILED"
    assert result["exit_code"] != 0
    assert calls == [
        ("h1", "000001"),
        ("h1", "000002"),
        ("h2", "000002"),
        ("h1", "000003"),
    ]
    assert result["by_symbol"]["000001"]["status"] == "UPDATED"
    assert result["by_symbol"]["000003"]["status"] == "UPDATED"
    assert result["by_symbol"]["000001"]["target_date_ready"] is True
    assert result["by_symbol"]["000003"]["target_date_ready"] is True
    assert targets[1].path.read_bytes() == symbol2_original
    assert len(result["failures"]) == 1
    assert {
        key: result["failures"][0][key]
        for key in ("symbol", "host", "failure_type")
    } == {
        "symbol": "000002",
        "host": "h2:7709",
        "failure_type": "target_date_missing",
    }
    assert result["failures"][0]["reason_code"] == "TARGET_DATE_MISSING"


def test_continuity_anomaly_is_reported_without_writing(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    target = DailyTarget(code="000003", market=0, path=tmp_path / "000003.day")
    _write_day(target.path, [_bar(20260818, 10.0)])
    original = target.path.read_bytes()
    scripts = {
        ("h1", "000003"): [[]],
        ("h2", "000003"): [[_bar(20260819, 100.0)]],
    }
    result = run_sync(
        [target],
        target_date="20260819",
        api_factory=lambda host, _port: _FakeSession(host, scripts, []),
        host_candidates=(("h1", 7709), ("h2", 7709)),
    )

    assert result["status"] == "FAILED"
    assert result["exit_code"] != 0
    assert target.path.read_bytes() == original
    assert result["failures"][0]["failure_type"] == "continuity_close_ratio"


def test_formal_run_uses_bounded_engine_and_state_owned_run_dir(tmp_path: Path, monkeypatch) -> None:
    import ops.a_share_daily_sync as sync

    day_path = tmp_path / "tdx" / "vipdoc" / "sz" / "lday" / "sz000002.day"
    _write_day(day_path, [_bar(20260818, 10.0)])
    scripts = {("h1", "000002"): [[_bar(20260819, 10.4)]]}
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(sync, "RUN_DIR", tmp_path / "state" / "a-sync-run")
    monkeypatch.setattr(
        sync,
        "_runtime_api_factory",
        lambda host, _port: _FakeSession(host, scripts, calls),
    )
    monkeypatch.setattr(sync, "_runtime_host_candidates", lambda _preferred: [("h1", 7709)])

    result = sync.run(
        argparse.Namespace(
            tdx_root=tmp_path / "tdx",
            target_date="20260819",
            markets="a",
            limit=0,
            host=None,
            timeout=1.5,
            count=20,
            dry_run=False,
            run_budget_seconds=12.5,
        )
    )

    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["budgets"]["run_budget_seconds"] == 12.5
    assert (tmp_path / "state" / "a-sync-run" / "summary.json").is_file()
    assert not (Path(sync.__file__).resolve().parent / "runs").exists()


def test_sync_main_propagates_nonzero_result(monkeypatch) -> None:
    import ops.a_share_daily_sync as sync

    monkeypatch.setattr(sync, "parse_args", lambda _argv=None: argparse.Namespace())
    monkeypatch.setattr(sync, "run", lambda _args: {"status": "FAILED", "exit_code": 2})
    assert sync.main([]) == 2


def test_after_1700_non_ready_statuses_are_nonzero() -> None:
    from ops.macos_research_panel_daily import ensure_exit_code

    for status in ("ALREADY_ATTEMPTED", "RETRY_BACKOFF", "ATTEMPTED"):
        assert ensure_exit_code({"status": status, "selector_pointer_ready": False}) != 0
    assert ensure_exit_code({"status": "ALREADY_READY", "selector_pointer_ready": True}) == 0
    assert ensure_exit_code({
        "status": "ATTEMPTED",
        "selector_pointer_ready": True,
        "backtest_pointer_ready": False,
    }) != 0


def test_after_1700_attempt_seam_stays_nonzero_until_exact_pointer_is_ready(tmp_path: Path, monkeypatch) -> None:
    import ops.macos_research_panel_daily as daily

    monkeypatch.setattr(daily, "selector_pointer_is_ready", lambda *_args: False)
    result = daily.ensure_after_1700(
        target_date="20260819",
        receipt_root=tmp_path / "receipts",
        selector_pointer=tmp_path / "selector.current",
        a_runner=lambda _target: {"status": "READY"},
        hk_runner=lambda _target: {"status": "READY"},
        now=daily._datetime.datetime(2026, 8, 19, 18, 0, tzinfo=daily.ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "ATTEMPTED"
    assert result["selector_pointer_ready"] is False
    assert daily.ensure_exit_code(result) != 0


def test_after_1700_retries_after_three_old_attempts(tmp_path: Path, monkeypatch) -> None:
    import json

    import ops.macos_research_panel_daily as daily

    monkeypatch.setattr(daily, "selector_pointer_is_ready", lambda *_args: False)
    attempt_path = tmp_path / "receipts" / "after_1700_ensure" / "20260819.json"
    attempt_path.parent.mkdir(parents=True)
    attempt_path.write_text(
        json.dumps(
            {
                "attempt_count": 3,
                "observed_at": "2026-08-19T17:00:00+08:00",
                "overall_status": "PARTIAL",
            }
        ),
        encoding="utf-8",
    )
    called: list[str] = []
    result = daily.ensure_after_1700(
        target_date="20260819",
        receipt_root=tmp_path / "receipts",
        selector_pointer=tmp_path / "selector.current",
        a_runner=lambda target: called.append(f"A:{target}") or {"status": "READY"},
        hk_runner=lambda target: called.append(f"HK:{target}") or {"status": "READY"},
        now=daily._datetime.datetime(2026, 8, 19, 18, 0, tzinfo=daily.ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "ATTEMPTED"
    assert result["attempt_count"] == 4
    assert called == ["A:20260819", "HK:20260819"]
    assert daily.ensure_exit_code(result) != 0


def test_after_1700_all_does_not_short_circuit_hk_when_a_selector_is_ready(
    tmp_path: Path, monkeypatch
) -> None:
    import ops.macos_research_panel_daily as daily

    monkeypatch.setattr(daily, "selector_pointer_is_ready", lambda *_args: True)
    calls: list[str] = []
    now = daily._datetime.datetime(2026, 8, 19, 18, 0, tzinfo=daily.ZoneInfo("Asia/Shanghai"))

    result = daily.ensure_after_1700(
        target_date="20260819",
        receipt_root=tmp_path / "receipts",
        selector_pointer=tmp_path / "selector.current",
        lane="ALL",
        now=now,
        a_runner=lambda target: calls.append("A") or {
            "status": "READY",
            "target_date": target,
            "formula": {"backtest_pointer_ready": True},
            "row_count": 1,
            "coverage_rate": 1.0,
            "sha256": "a" * 64,
        },
        hk_runner=lambda target: calls.append("HK") or {
            "status": "READY",
            "target_date": target,
            "row_count": 1,
            "coverage_rate": 1.0,
            "sha256": "b" * 64,
        },
    )

    assert calls == ["A", "HK"]
    assert result["status"] == "ATTEMPTED"
    assert result["hk_lane_ready"] is True
    assert daily.ensure_exit_code(result) == 0


def test_after_1700_hk_requires_exact_valid_dated_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    import ops.macos_research_panel_daily as daily

    monkeypatch.setattr(daily, "selector_pointer_is_ready", lambda *_args: True)
    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir(parents=True)
    (receipt_root / "hk-20260819.json").write_text(
        json.dumps(
            {
                "status": "READY",
                "target_date": "20260818",
                "row_count": 0,
                "coverage_rate": 0.0,
                "sha256": "",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []
    result = daily.ensure_after_1700(
        target_date="20260819",
        receipt_root=receipt_root,
        selector_pointer=tmp_path / "selector.current",
        lane="HK",
        now=daily._datetime.datetime(2026, 8, 19, 18, 0, tzinfo=daily.ZoneInfo("Asia/Shanghai")),
        a_runner=lambda _target: calls.append("A") or {"status": "READY"},
        hk_runner=lambda target: calls.append("HK") or {
            "status": "READY",
            "target_date": target,
            "row_count": 1,
            "coverage_rate": 1.0,
            "sha256": "c" * 64,
        },
    )

    assert calls == ["HK"]
    assert result["status"] == "ATTEMPTED"
    assert result["hk_lane_ready"] is True


def test_after_1700_a_requires_backtest_readiness_even_when_selector_is_ready(
    tmp_path: Path, monkeypatch
) -> None:
    import ops.macos_research_panel_daily as daily

    monkeypatch.setattr(daily, "selector_pointer_is_ready", lambda *_args: True)
    calls: list[str] = []
    result = daily.ensure_after_1700(
        target_date="20260819",
        receipt_root=tmp_path / "receipts",
        selector_pointer=tmp_path / "selector.current",
        lane="A",
        now=daily._datetime.datetime(2026, 8, 19, 18, 0, tzinfo=daily.ZoneInfo("Asia/Shanghai")),
        a_runner=lambda target: calls.append(target) or {
            "status": "READY",
            "target_date": target,
            "formula": {"backtest_pointer_ready": False},
            "row_count": 1,
            "coverage_rate": 1.0,
            "sha256": "d" * 64,
        },
        hk_runner=lambda _target: (_ for _ in ()).throw(AssertionError("HK not requested")),
    )

    assert calls == ["20260819"]
    assert result["status"] == "ATTEMPTED"
    assert result["a_lane_ready"] is False
    assert daily.ensure_exit_code(result) != 0


def test_strict_scope_rejects_duplicate_target_identity_before_provider(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    path = tmp_path / "000015.day"
    target = DailyTarget(code="000015", market=0, path=path)
    with pytest.raises(ValueError, match="A_SYNC_TARGET_SCOPE_DUPLICATE"):
        run_sync(
            [target, target],
            target_date="20260911",
            api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("provider must not open")),
            host_candidates=(("h1", 7709),),
        )


def test_strict_local_field_signature_blocks_provider_and_binds_source_sha(tmp_path: Path) -> None:
    import struct

    from ops.a_share_daily_sync import DAY_STRUCT, DailyTarget, pack_hq_bar, run_sync

    path = tmp_path / "000016.day"
    raw = bytearray(pack_hq_bar(_bar(20260910, 10.0)))
    struct.pack_into("<I", raw, 20, 0x00400000)
    struct.pack_into("<I", raw, 24, 0)
    path.write_bytes(bytes(raw))
    original = path.read_bytes()
    target = DailyTarget(code="000016", market=0, path=path)
    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("field failure must precede provider")),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "progress.json",
    )

    assert result["status"] == "FAILED"
    row = result["by_symbol"]["000016"]
    assert row["failure_type"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert row["field_violations"][0]["native_file_sha256"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
    assert len(original) == DAY_STRUCT.size


def test_strict_progress_binds_source_sha_and_reuses_current_target(tmp_path: Path) -> None:
    import json

    from ops.a_share_daily_sync import DailyTarget, run_sync

    path = tmp_path / "000017.day"
    _write_day(path, [_bar(20260910, 10.0)])
    target = DailyTarget(code="000017", market=0, path=path)
    progress = tmp_path / "progress.json"
    result = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda _host, _port: _FakeSession(
            "h1", {("h1", "000017"): [[_bar(20260911, 10.2)]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )

    assert result["status"] == "PASS"
    saved = json.loads(progress.read_text())
    entry = saved["symbol_progress"]["000017"]
    assert saved["target_fingerprint"]
    assert entry["source_sha256_before"]
    assert entry["source_sha256_after"]
    assert saved["completed_symbols"] == ["000017"]
    second = run_sync(
        [target],
        target_date="20260911",
        api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("current target must not open")),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert second["status"] == "PASS"
    assert second["by_symbol"]["000017"]["status"] == "ALREADY_CURRENT"


def test_strict_cas_descriptor_rejects_unbound_schema_before_provider(tmp_path: Path) -> None:
    import json

    from ops.a_share_daily_sync import DailyTarget, run_sync

    path = tmp_path / "000018.day"
    _write_day(path, [_bar(20260910, 10.0)])
    cas = tmp_path / "cas.json"
    cas.write_text(json.dumps({"schema_version": "unbound"}))
    with pytest.raises(ValueError, match="A_SYNC_TRUSTED_CAS_INPUTS_SCHEMA_MISMATCH"):
        run_sync(
            [DailyTarget(code="000018", market=0, path=path)],
            target_date="20260911",
            api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("CAS must fail before provider")),
            host_candidates=(("h1", 7709),),
            trusted_cas_inputs=cas,
        )


# These fixtures reproduce the accepted snapshot -> committed adoption -> raw
# provider/source binding without reading live state or issuing provider calls.
def _seed_fixture(tmp_path, *, code='002335', market='SZ', previous=60.5, close=39.06,
                  previous_date=20260528, current_date=20260529, a=0.68966, b=-0.34483):
    import json
    from ops.a_share_daily_sync import pack_hq_bar

    def save(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    symbol = f'{code}.{market}'
    bars = [_bar(previous_date, previous), _bar(current_date, close)]
    seed = tmp_path / f'{code}.day'
    _write_day(seed, bars)
    archive = tmp_path / f'{symbol}.day'
    # Full accepted history differs in size/reserved bytes, but the actual
    # pair closes are identical.  File equality must not be a prerequisite.
    archive.write_bytes(pack_hq_bar(_bar(20250102, previous)) + b''.join(
        pack_hq_bar(bar)[:-4] + b'\x01\x00\x00\x00' for bar in bars))
    rawref = {'path': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'source_role': 'archive'}
    event = {'ex_date': current_date, 'a': a, 'b': b, 'volume_a': 1.45}
    daytext = f'{current_date // 10000:04}-{current_date // 100 % 100:02}-{current_date % 100:02}'
    response = {'code': f'{market}.{code}', 'source': 'Futu OpenD get_rehab', 'return_code': 0,
                'rows': [{'ex_div_date': daytext, 'forward_adj_factorA': a,
                          'forward_adj_factorB': b, 'backward_adj_factorA': 1.45}]}
    item = {'history_start_date': 20250102, 'history_end_date': 20260630,
            'event_coverage_complete': True, 'source_method': 'FUTU_GET_REHAB_AFFINE',
            'raw_resolution': 'ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2',
            'events': [event], 'raw_files': [rawref]}
    snapshot = {'schema': 'a_share_qfq_adjustment_input_v1', 'price_basis': 'QFQ_ASOF',
                'convention': 'FUTU_AFFINE_WITH_EXPLICIT_TDX_UNSUPPORTED_FALLBACK_V1',
                'asof_date': 20260630, 'coverage_end_date': 20260630, 'symbols': {symbol: item}}
    snapshotref = save('snapshot.json', snapshot)
    response_ref = save('provider.json', response)
    checkpoint = {'asof_date': 20260630, 'symbols': {symbol: {'status': 'OK', 'asof_date': 20260630, 'response': response_ref}}}
    checkpointref = save('checkpoint.json', checkpoint)
    journal = {'status': 'COMMITTED', 'metadata': [{'path': '/accepted/qfq_adjustment_input.json', 'after': snapshotref}]}
    journalref = save('journal.json', journal)
    receipt = {'schema': 'ACTUAL_COUPLED_ADOPTION_READBACK_R1',
               'status': 'COMMITTED_PAIR_AND_FIVE_METADATA_READBACK_MATCH', 'journal_status': 'COMMITTED',
               'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
               'five_metadata': [{'path': '/accepted/qfq_adjustment_input.json', 'sha256': snapshotref['sha256']}],
               'roles': {role: {'generation_id': 'test-generation', 'input_sha256': 'e' * 64} for role in ('selector', 'backtest')},
               'journal': journalref}
    receiptref = save('receipt.json', receipt)
    descriptor = {'schema_version': 'a_share_daily_sync.seed_adjustment_evidence.v1',
                  'snapshot': snapshotref, 'adoption_receipt': receiptref, 'factor_cache_checkpoint': checkpointref}
    descriptorref = save('descriptor.json', descriptor)
    return locals()


def _rewrite_seed_fixture(f):
    """Rebind the fixture's trust chain after an intentional semantic mutation."""
    for name, value in [('snapshot', f['snapshot']), ('response', f['response'])]:
        ref = f['save']('snapshot.json' if name == 'snapshot' else 'provider.json', value)
        f[name + 'ref' if name == 'snapshot' else 'response_ref'] = ref
    f['checkpoint']['symbols'][f['symbol']]['response'] = f['response_ref']
    f['journal']['metadata'][0]['after'] = f['snapshotref']
    f['receipt']['five_metadata'][0]['sha256'] = f['snapshotref']['sha256']
    f['receipt']['journal'] = f['save']('journal.json', f['journal'])
    f['descriptor']['snapshot'] = f['snapshotref']
    f['descriptor']['adoption_receipt'] = f['save']('receipt.json', f['receipt'])
    f['descriptor']['factor_cache_checkpoint'] = f['save']('checkpoint.json', f['checkpoint'])
    f['descriptorref'] = f['save']('descriptor.json', f['descriptor'])


@pytest.mark.parametrize('code,market,previous,close,previous_date,current_date,a,b', [
    ('002335', 'SZ', 60.5, 39.06, 20260528, 20260529, 0.68966, -0.34483),
    ('600123', 'SH', 80.0, 40.1, 20260611, 20260612, 0.5, -0.2),
])
def test_seed_affine_explains_only_bound_pair_without_rewriting(tmp_path, code, market, previous, close,
                                                              previous_date, current_date, a, b):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path, code=code, market=market, previous=previous, close=close,
                      previous_date=previous_date, current_date=current_date, a=a, b=b)
    original = f['seed'].read_bytes()
    assert sync._local_history_status(f['seed'], 20260701)[1] == sync.CROSS_DAY_CLOSE_RATIO
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    bars, failure = sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])
    assert failure is None
    assert len(bars) == 2 and f['seed'].read_bytes() == original
    record = context['records'][0]
    assert record['transformed_previous_close'] == pytest.approx(previous * a + b)
    assert record['transformed_ratio'] == pytest.approx(close / (previous * a + b))
    assert record['pair_sources'][0]['row_index'] == 1
    assert record['snapshot']['sha256'] == f['snapshotref']['sha256']
    assert record['provider_response'] == f['response_ref']


@pytest.mark.parametrize('problem', [
    'missing_descriptor', 'sha', 'uncommitted', 'journal', 'adoption_pair', 'snapshot_not_adopted',
    'wrong_code', 'provider_conflict', 'provider_missing', 'duplicate_event', 'coverage',
    'history_start', 'raw_basis', 'raw_sha', 'negative_a', 'nan_b', 'nonpositive_denominator',
    'unexplained', 'unknown_policy', 'future_snapshot',
])
def test_seed_affine_missing_conflicting_or_invalid_evidence_keeps_original_failure(tmp_path, problem):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    if problem == 'uncommitted': f['receipt']['status'] = 'STAGED'
    elif problem == 'journal': f['journal']['status'] = 'PREPARED'
    elif problem == 'adoption_pair': f['receipt']['roles']['backtest']['generation_id'] = 'other'
    elif problem == 'snapshot_not_adopted': f['receipt']['five_metadata'][0]['path'] = '/wrong.json'
    elif problem == 'wrong_code': f['response']['code'] = 'SH.002335'
    elif problem == 'provider_conflict': f['response']['rows'][0]['forward_adj_factorA'] = 0.5
    elif problem == 'provider_missing': f['response']['rows'] = []
    elif problem == 'duplicate_event': f['item']['events'].append(dict(f['event']))
    elif problem == 'coverage': f['snapshot']['coverage_end_date'] = 20260528
    elif problem == 'history_start': f['item']['history_start_date'] = 20260529
    elif problem == 'raw_basis':
        _write_day(f['archive'], [_bar(20260528, 61.0), _bar(20260529, 39.06)])
        f['rawref']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
    elif problem == 'raw_sha': f['rawref']['sha256'] = '0' * 64
    elif problem in ('negative_a', 'nan_b', 'nonpositive_denominator', 'unexplained'):
        a, b = {'negative_a': (-1., 0.), 'nan_b': (0.68966, float('nan')),
                'nonpositive_denominator': (0.5, -100.), 'unexplained': (1., 0.)}[problem]
        f['event'].update(a=a, b=b)
        f['response']['rows'][0].update(forward_adj_factorA=a, forward_adj_factorB=b)
    elif problem == 'unknown_policy': f['item']['raw_resolution'] = 'LATEST_ROW_WINS'
    elif problem == 'future_snapshot':
        f['snapshot']['asof_date'] = 20270101
        f['checkpoint']['asof_date'] = 20270101
        f['checkpoint']['symbols'][f['symbol']]['asof_date'] = 20270101
    _rewrite_seed_fixture(f)
    if problem == 'sha': f['archive'].write_bytes(f['archive'].read_bytes() + b'junk')
    context = {'path': str(tmp_path / 'missing.json') if problem == 'missing_descriptor' else f['descriptorref']['path'],
               'expected_sha256': f['descriptorref']['sha256']}
    original = f['seed'].read_bytes()
    assert sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][0]['status'] == 'UNEXPLAINED'
    assert f['seed'].read_bytes() == original


@pytest.mark.parametrize('later_failure', ['ohlc', 'duplicate', 'order', 'future', 'jump'])
def test_seed_explanation_does_not_skip_later_original_gates(tmp_path, later_failure):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    bar = _bar(20260601, 39.2)
    if later_failure == 'ohlc': bar['high'] = 20.0
    elif later_failure == 'duplicate': bar = _bar(20260529, 39.06)
    elif later_failure == 'order': bar = _bar(20260528, 60.5)
    elif later_failure == 'future': bar = _bar(20260702, 39.2)
    elif later_failure == 'jump': bar = _bar(20260601, 10.0)
    f['seed'].write_bytes(f['seed'].read_bytes() + sync.pack_hq_bar(bar))
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    _bars, failure = sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])
    assert failure is not None
    assert context['records'][0]['status'] == 'EXPLAINED_ACCEPTED_AFFINE'


def test_seed_accepted_archive_policy_cannot_cherry_pick_native_conflict(tmp_path):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    f['item']['raw_files'].append({'path': str(f['seed']), 'sha256': hashlib.sha256(f['seed'].read_bytes()).hexdigest(), 'source_role': 'native'})
    _write_day(f['archive'], [_bar(20260528, 70.), _bar(20260529, 39.06)])
    f['rawref']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
    _rewrite_seed_fixture(f)
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    assert sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][0]['reason'] == 'pair_raw_basis_conflict'


def test_seed_two_events_compose_chronologically_for_generic_pair(tmp_path):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path, previous=80., close=20., a=.5, b=-.2)
    f['item']['events'].insert(0, {'ex_date': 20260528, 'a': .5, 'b': 0., 'volume_a': 2.})
    # Move the first pair date before both events; use accepted source bytes.
    _write_day(f['seed'], [_bar(20260527, 80.), _bar(20260529, 20.)])
    _write_day(f['archive'], [_bar(20260527, 80.), _bar(20260529, 20.)])
    f['rawref']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
    f['response']['rows'].insert(0, {'ex_div_date': '2026-05-28', 'forward_adj_factorA': .5, 'forward_adj_factorB': 0., 'backward_adj_factorA': 2.})
    _rewrite_seed_fixture(f)
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    assert sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])[1] is None
    assert context['records'][0]['transformed_previous_close'] == pytest.approx(19.8)


@pytest.mark.parametrize('bad_field,new_bar_jump', [(False, False), (True, False), (False, True)])
def test_seed_run_sync_preserves_fields_newbars_and_persists_explanation(tmp_path, monkeypatch, bad_field, new_bar_jump):
    import struct
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    f['snapshot']['asof_date'] = f['snapshot']['coverage_end_date'] = 20260529
    f['checkpoint']['asof_date'] = f['checkpoint']['symbols'][f['symbol']]['asof_date'] = 20260529
    _rewrite_seed_fixture(f)
    if bad_field:
        raw = bytearray(f['seed'].read_bytes())
        struct.pack_into('<I', raw, 20, 0x00400000)
        struct.pack_into('<I', raw, 24, 0)
        f['seed'].write_bytes(raw)
    original = f['seed'].read_bytes()
    calls = []
    scripts = {('h1', '002335'): [[_bar(20260529, 39.06), _bar(20260601, 10. if new_bar_jump else 39.2)]]}
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    result = sync.run_sync([sync.DailyTarget(code='002335', market=0, path=f['seed'])],
                           target_date='20260601', api_factory=lambda host, _port: _FakeSession(host, scripts, calls),
                           host_candidates=(('h1', 7709),), progress_path=tmp_path / 'progress.json',
                           seed_adjustment_inputs=f['descriptorref']['path'],
                           seed_adjustment_inputs_sha256=f['descriptorref']['sha256'])
    assert result['seed_adjustment_evidence']['records'][0]['status'] == 'EXPLAINED_ACCEPTED_AFFINE'
    assert result['progress']['seed_ratio_explanations']['002335'][0]['status'] == 'EXPLAINED_ACCEPTED_AFFINE'
    if bad_field or new_bar_jump:
        assert result['status'] == 'FAILED'
        assert f['seed'].read_bytes() == original
        expected = sync.KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE if bad_field else sync.CROSS_DAY_CLOSE_RATIO
        assert result['by_symbol']['002335']['reason_code'] == expected
        assert result['by_symbol']['002335']['failure_type'] == (expected if bad_field else 'continuity_close_ratio')
        assert calls == ([] if bad_field else [('h1', '002335')])
    else:
        assert result['status'] == 'PASS'
        assert result['by_symbol']['002335']['records_written'] == 1
        assert f['seed'].read_bytes().startswith(original)
        assert calls == [('h1', '002335')]


def test_seed_evidence_opt_in_cli_env_and_no_default_exemption(tmp_path, monkeypatch):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    args = sync.parse_args(['--target-date', '20260701', '--seed-adjustment-inputs', f['descriptorref']['path'],
                            '--seed-adjustment-inputs-sha256', f['descriptorref']['sha256']])
    assert args.seed_adjustment_inputs == Path(f['descriptorref']['path'])
    assert args.seed_adjustment_inputs_sha256 == f['descriptorref']['sha256']
    kwargs = dict(target_date='20260701', host_candidates=(('never', 7709),),
                  api_factory=lambda *_: (_ for _ in ()).throw(AssertionError('must not request')))
    # With no descriptor the old rejection still occurs before provider use.
    monkeypatch.delenv(sync.SEED_ADJUSTMENT_INPUTS_ENV, raising=False)
    monkeypatch.delenv(sync.SEED_ADJUSTMENT_INPUTS_SHA256_ENV, raising=False)
    result = sync.run_sync([sync.DailyTarget(code='002335', market=0, path=f['seed'])],
                           progress_path=tmp_path / 'strict.json', **kwargs)
    assert result['by_symbol']['002335']['reason_code'] == sync.CROSS_DAY_CLOSE_RATIO
    assert result['by_symbol']['002335']['failure_type'] == 'continuity_close_ratio'
    # A configured evidence path is lazy: ordinary valid seeds do not require
    # a snapshot and must not be broken by an unrelated unavailable binding.
    healthy = tmp_path / 'healthy.day'
    _write_day(healthy, [_bar(20260701, 10.)])
    monkeypatch.setenv(sync.SEED_ADJUSTMENT_INPUTS_ENV, str(tmp_path / 'absent.json'))
    result = sync.run_sync([sync.DailyTarget(code='000002', market=0, path=healthy)],
                           progress_path=tmp_path / 'healthy.json', **kwargs)
    assert result['status'] == 'PASS'
    assert result['seed_adjustment_evidence']['records'] == []


@pytest.mark.parametrize('pin', [None, '', 123, 'not-a-digest', '0' * 64])
def test_seed_external_pin_is_required_before_resolving_any_chain(tmp_path, monkeypatch, pin):
    import ops.a_share_daily_sync as sync
    from ops._a_share_daily_sync_parts import progress
    f = _seed_fixture(tmp_path)
    # If verification ever resolves a self-described reference before the
    # trusted external digest, this sentinel fails the test.
    monkeypatch.setattr(progress, '_evidence_json', lambda *_: (_ for _ in ()).throw(AssertionError('unapproved chain read')))
    context = {'path': f['descriptorref']['path'], 'expected_sha256': pin}
    assert sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][0]['reason'].startswith('external_descriptor_pin_')


def test_seed_fully_rehashed_replacement_chain_cannot_approve_itself(tmp_path):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    approved_pin = f['descriptorref']['sha256']
    # Replace provider coefficients, accepted snapshot, raw rows, journal and
    # receipt with a fully self-consistent new chain. Internal hashes all match.
    # This new chain would explain a different fabricated raw pair, but the
    # trusted invocation still authorizes ONLY the original descriptor bytes.
    f['event'].update(a=.5, b=0.)
    f['response']['rows'][0].update(forward_adj_factorA=.5, forward_adj_factorB=0.)
    _write_day(f['seed'], [_bar(20260528, 80.), _bar(20260529, 40.)])
    _write_day(f['archive'], [_bar(20260528, 80.), _bar(20260529, 40.)])
    f['rawref']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
    _rewrite_seed_fixture(f)
    assert f['descriptorref']['sha256'] != approved_pin
    # Even an alleged pin declared inside the replacement has no authority.
    f['descriptor']['expected_sha256'] = f['descriptorref']['sha256']
    f['descriptorref'] = f['save']('descriptor.json', f['descriptor'])
    context = {'path': f['descriptorref']['path'], 'expected_sha256': approved_pin}
    original = f['seed'].read_bytes()
    assert sync._local_history_status(f['seed'], 20260701, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][0]['reason'] == 'external_descriptor_pin_mismatch'
    assert f['seed'].read_bytes() == original


def test_seed_external_pin_flows_from_trusted_env_to_workflow(tmp_path, monkeypatch):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    monkeypatch.setenv(sync.SEED_ADJUSTMENT_INPUTS_ENV, f['descriptorref']['path'])
    monkeypatch.setenv(sync.SEED_ADJUSTMENT_INPUTS_SHA256_ENV, f['descriptorref']['sha256'])
    # The source itself ends at target, so a trusted pinned historical pair
    # can be accepted locally without creating a provider session.
    f['snapshot']['asof_date'] = f['snapshot']['coverage_end_date'] = 20260529
    f['checkpoint']['asof_date'] = f['checkpoint']['symbols'][f['symbol']]['asof_date'] = 20260529
    _rewrite_seed_fixture(f)
    monkeypatch.setenv(sync.SEED_ADJUSTMENT_INPUTS_SHA256_ENV, f['descriptorref']['sha256'])
    result = sync.run_sync([sync.DailyTarget(code='002335', market=0, path=f['seed'])], target_date='20260529',
                           api_factory=lambda *_: (_ for _ in ()).throw(AssertionError('no quote permitted')),
                           host_candidates=(('never', 7709),), progress_path=tmp_path / 'progress.json')
    assert result['status'] == 'PASS'
    assert result['seed_adjustment_evidence']['records'][0]['expected_descriptor_sha256'] == f['descriptorref']['sha256']


def test_seed_cli_forwards_approved_external_pin_without_changing_factory(tmp_path, monkeypatch):
    import ops.a_share_daily_sync as sync
    f = _seed_fixture(tmp_path)
    f['snapshot']['asof_date'] = f['snapshot']['coverage_end_date'] = 20260529
    f['checkpoint']['asof_date'] = f['checkpoint']['symbols'][f['symbol']]['asof_date'] = 20260529
    _rewrite_seed_fixture(f)
    day = tmp_path / 'tdx/vipdoc/sz/lday/sz002335.day'
    day.parent.mkdir(parents=True)
    day.write_bytes(f['seed'].read_bytes())
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    monkeypatch.setattr(sync, '_runtime_host_candidates', lambda _: [('never', 7709)])
    monkeypatch.setattr(sync, '_runtime_api_factory', lambda *_: (_ for _ in ()).throw(AssertionError('no quote permitted')))
    args = sync.parse_args(['--target-date', '20260529', '--tdx-root', str(tmp_path / 'tdx'),
                            '--seed-adjustment-inputs', f['descriptorref']['path'],
                            '--seed-adjustment-inputs-sha256', f['descriptorref']['sha256']])
    result = sync.run(args)
    assert result['status'] == 'PASS'
    assert result['seed_adjustment_evidence']['records'][0]['status'] == 'EXPLAINED_ACCEPTED_AFFINE'


def _ipo_docx(path, paragraphs):
    import zipfile
    from xml.sax.saxutils import escape
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    xml += ''.join('<w:p><w:r><w:t>' + escape(p) + '</w:t></w:r></w:p>' for p in paragraphs)
    xml += '</w:body></w:document>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _ipo_fixture(tmp_path, *, code='601091', sessions=None):
    import json
    import os
    if sessions is None:
        sessions = [20260917, 20260918, 20260921, 20260922, 20260923, 20260924]
    f = _seed_fixture(tmp_path, code=code, market='SH', previous=20.8, close=57.77,
                      previous_date=sessions[0], current_date=sessions[1], a=1., b=0.)
    f['snapshot']['asof_date'] = f['snapshot']['coverage_end_date'] = 20261023
    f['checkpoint']['asof_date'] = f['checkpoint']['symbols'][f['symbol']]['asof_date'] = 20261023
    listing = sessions[0]
    closes = [20.8, 57.77, 37.72, 37.98, 30., 29.5]
    bars = [_bar(day, close) for day, close in zip(sessions, closes)]
    _write_day(f['seed'], bars)
    _write_day(f['archive'], bars)
    def ref(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    rawref = ref(f['archive'])
    metadata = {'normalization_status': 'NORMALIZED', 'source_row_id': 'sse_type1_export:股票:1',
                'canonical_fields': {'ts_code': f['symbol'], 'security_code': code, 'listing_date': str(listing)}}
    disclosure = {'SECURITY_CODE': code, 'BULLETIN_TYPE_DESC': '首次公开发行',
                  'TITLE': '测试公司首次公开发行股票主板上市公告书', 'SSEDATE': '2026-09-01',
                  'URL': '/disclosure/listedinfo/announcement/c/new/test/listing.pdf'}
    index = {'result': [[disclosure]]}
    capture = {'url': 'https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do?SECURITY_CODE=' + code + '&BULLETIN_TYPE=08&jsonCallBack=IPO_FIXTURE', 'http_status': 200}
    notice = '<div class="allZoom">证券代码为"' + code + '"，于' + str(listing // 10000) + '年' + str(listing // 100 % 100) + '月' + str(listing % 100) + '日起上市交易。</div>'
    review = {'schema': 'REVIEWER_TYPED_SAME_INPUT_PASS_REUSE_R1', 'verdict': 'REVIEWED/PASS_ARCHIVE_ONLY_SOURCE_KEYS_AND_BYTES',
              'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
              'codes': {f['symbol']: {'raw32_sha256': rawref['sha256'], 'rows': len(bars), 'first_date': sessions[0], 'last_date': sessions[-1]}}}
    resolver = Path(os.environ.get('IPO_SEED_TEST_CALENDAR_RESOLVER', str(Path(__file__).resolve().parents[1] / 'contracts/trading_calendar.py')))
    calendar = Path(os.environ.get('IPO_SEED_TEST_CALENDAR_JSON', str(resolver.with_name('market_calendar_2026.json'))))
    rule_doc = _ipo_docx(tmp_path / 'rule.docx', ['3.3.13 本所实行涨跌幅限制。', '属于下列情形的股票，不实行价格涨跌幅限制：',
                    '首次公开发行上市的股票上市后的前5个交易日', '3.3.14 其他。', '本规则自2026年7月6日起施行。'])
    deferred_doc = _ipo_docx(tmp_path / 'deferred.docx', ['3.6.2 暂缓条文。'])
    spec = {'type': 'SSE_MAIN_BOARD_FIRST_IPO_FIRST_FIVE_SESSIONS', 'listing_date': listing,
            'source_row_id': metadata['source_row_id'], 'ipo_document_href': disclosure['URL'],
            'rule': {'type': 'SSE_MAIN_BOARD_FIRST_IPO_NO_PRICE_LIMIT', 'article': '3.3.13', 'sessions': 5,
                     'effective_from': 20260706, 'verified_through': 20261023, 'document': rule_doc, 'deferred_document': deferred_doc},
            'calendar': {'resolver': ref(resolver), 'data': ref(calendar)}, 'raw_source': rawref}
    f.update(ipo_metadata=metadata, ipo_index=index, ipo_capture=capture, ipo_notice=notice, ipo_review=review,
             ipo_spec=spec, ipo_bars=bars, ipo_sessions=sessions)
    f['descriptor']['ipo_seed_boundaries'] = {f['symbol']: spec}
    _rebind_ipo_fixture(f)
    return f


def _rebind_ipo_fixture(f):
    import json
    tmp = f['tmp_path']
    f['ipo_spec']['listing_metadata'] = f['save']('ipo_metadata.jsonl', f['ipo_metadata'])
    path = tmp / 'ipo_index.jsonp'
    path.write_text('IPO_FIXTURE(' + json.dumps(f['ipo_index'], ensure_ascii=False) + ')', encoding='utf-8')
    f['ipo_spec']['ipo_index'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    f['ipo_capture']['sha256'] = f['ipo_spec']['ipo_index']['sha256']
    f['ipo_spec']['ipo_index_capture'] = f['save']('ipo_capture.json', f['ipo_capture'])
    path = tmp / 'listing_notice.html'
    path.write_text(f['ipo_notice'], encoding='utf-8')
    f['ipo_spec']['listing_notice'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    f['ipo_spec']['raw_review'] = f['save']('raw_review.json', f['ipo_review'])
    _rewrite_seed_fixture(f)


@pytest.mark.parametrize('code,sessions', [
    ('601091', [20260917, 20260918, 20260921, 20260922, 20260923, 20260924]),
    ('603448', [20260907, 20260908, 20260909, 20260910, 20260911, 20260914]),
])
def test_ipo_history_primary_calendar_explains_only_typed_window(tmp_path, code, sessions):
    import ops.a_share_daily_sync as sync
    f = _ipo_fixture(tmp_path, code=code, sessions=sessions)
    original = f['seed'].read_bytes()
    assert sync._local_history_status(f['seed'], 20261024)[1] == sync.CROSS_DAY_CLOSE_RATIO
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    bars, failure = sync._local_history_status(f['seed'], 20261024, seed_evidence=context, symbol=f['symbol'])
    assert failure is None and len(bars) == 6
    assert f['seed'].read_bytes() == original
    assert len(context['records']) == 2
    for record in context['records']:
        assert record['status'] == 'EXPLAINED_IPO_FIRST_FIVE_SESSIONS'
        assert record['market_first_five_sessions'] == sessions[:5]
        assert record['current_session_ordinal'] in (2, 3)
        assert 'events' not in record and 'transformed_ratio' not in record
    assert context['records'][0]['raw_ratio'] == pytest.approx(57.77 / 20.8)


@pytest.mark.parametrize('problem', [
    'missing_primary', 'relisting', 'current_list_only', 'wrong_index_code', 'wrong_notice_code',
    'wrong_notice_date', 'wrong_index_origin', 'metadata_listing_conflict', 'truncated_seed',
    'missing_seed_session', 'missing_raw_session', 'raw_basis_conflict', 'raw_review_conflict',
    'raw_sha', 'calendar_sha', 'resolver_sha', 'calendar_year', 'listing_on_closed_day',
    'rule_not_effective', 'rule_date_conflict', 'rule_deferred', 'rule_missing_clause', 'wrong_market',
    'missing_later_seed_session', 'missing_later_raw_session',
])
def test_ipo_history_unknown_or_conflicting_dependencies_keep_original_gate(tmp_path, problem):
    import json
    import ops.a_share_daily_sync as sync
    f = _ipo_fixture(tmp_path)
    if problem in ('missing_primary', 'current_list_only'):
        f['ipo_index']['result'] = []
    elif problem == 'relisting': f['ipo_index']['result'][0][0]['BULLETIN_TYPE_DESC'] = '重新上市'
    elif problem == 'wrong_index_code': f['ipo_index']['result'][0][0]['SECURITY_CODE'] = '601092'
    elif problem == 'wrong_notice_code': f['ipo_notice'] = f['ipo_notice'].replace('601091', '601092')
    elif problem == 'wrong_notice_date': f['ipo_notice'] = f['ipo_notice'].replace('9月17日', '9月16日')
    elif problem == 'wrong_index_origin': f['ipo_capture']['url'] = f['ipo_capture']['url'].replace('query.sse.com.cn', 'example.org')
    elif problem == 'metadata_listing_conflict': f['ipo_metadata']['canonical_fields']['listing_date'] = '20260916'
    elif problem == 'truncated_seed': _write_day(f['seed'], f['ipo_bars'][1:])
    elif problem == 'missing_seed_session': _write_day(f['seed'], f['ipo_bars'][:1] + f['ipo_bars'][2:])
    elif problem == 'missing_later_seed_session': _write_day(f['seed'], f['ipo_bars'][:3] + f['ipo_bars'][4:])
    elif problem in ('missing_raw_session', 'missing_later_raw_session', 'raw_basis_conflict'):
        bars = list(f['ipo_bars'])
        if problem == 'missing_raw_session': bars = bars[1:]
        elif problem == 'missing_later_raw_session': bars = bars[:3] + bars[4:]
        else: bars[0] = _bar(f['ipo_sessions'][0], 21.)
        _write_day(f['archive'], bars)
        f['ipo_spec']['raw_source']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
        f['ipo_review']['codes'][f['symbol']].update(raw32_sha256=f['ipo_spec']['raw_source']['sha256'], rows=len(bars), first_date=sync.day_int(bars[0]))
    elif problem == 'raw_review_conflict': f['ipo_review']['codes'][f['symbol']]['raw32_sha256'] = '0' * 64
    elif problem == 'raw_sha': f['ipo_spec']['raw_source']['sha256'] = '0' * 64
    elif problem == 'calendar_sha': f['ipo_spec']['calendar']['data']['sha256'] = '0' * 64
    elif problem == 'resolver_sha': f['ipo_spec']['calendar']['resolver']['sha256'] = '0' * 64
    elif problem in ('calendar_year', 'listing_on_closed_day'):
        path = Path(f['ipo_spec']['calendar']['data']['path'])
        data = json.loads(path.read_text())
        if problem == 'calendar_year': data['year'] = 2025
        else: data['markets']['a_share']['holiday_periods'].append({'name': 'test_closed', 'start': '20260917', 'end': '20260917'})
        f['ipo_spec']['calendar']['data'] = f['save']('wrong_calendar.json', data)
    elif problem == 'rule_not_effective':
        f['ipo_spec']['rule']['effective_from'] = 20261001
        f['ipo_spec']['rule']['document'] = _ipo_docx(tmp_path / 'future_rule.docx', ['3.3.13 不实行价格涨跌幅限制：', '首次公开发行上市的股票上市后的前5个交易日', '3.3.14 其他', '本规则自2026年10月1日起施行。'])
    elif problem == 'rule_date_conflict': f['ipo_spec']['rule']['effective_from'] = 20260707
    elif problem == 'rule_deferred': f['ipo_spec']['rule']['deferred_document'] = _ipo_docx(tmp_path / 'wrong_deferred.docx', ['3.3.13 暂缓实施'])
    elif problem == 'rule_missing_clause': f['ipo_spec']['rule']['document'] = _ipo_docx(tmp_path / 'wrong_rule.docx', ['3.3.13 一般股票', '3.3.14 其他', '本规则自2026年7月6日起施行。'])
    elif problem == 'wrong_market': f['ipo_spec']['type'] = 'OTHER_EXCHANGE_IPO'
    _rebind_ipo_fixture(f)
    original = f['seed'].read_bytes()
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    assert sync._local_history_status(f['seed'], 20261024, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][-1]['status'] == 'UNEXPLAINED'
    assert f['seed'].read_bytes() == original


@pytest.mark.parametrize('problem', ['day_five_to_six', 'five_stock_bars_not_five_sessions', 'later_bad_ohlc', 'later_duplicate', 'later_future'])
def test_ipo_history_does_not_extend_window_or_skip_later_rows(tmp_path, problem):
    import ops.a_share_daily_sync as sync
    f = _ipo_fixture(tmp_path)
    bars = list(f['ipo_bars'])
    if problem in ('day_five_to_six', 'five_stock_bars_not_five_sessions'):
        bars[-1] = _bar(f['ipo_sessions'][-1], 90.)
        _write_day(f['archive'], bars)
        f['ipo_spec']['raw_source']['sha256'] = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
        f['ipo_review']['codes'][f['symbol']]['raw32_sha256'] = f['ipo_spec']['raw_source']['sha256']
        if problem == 'five_stock_bars_not_five_sessions': bars = bars[:1] + bars[2:]
    elif problem == 'later_bad_ohlc': bars[-1] = dict(bars[-1], high=1.)
    elif problem == 'later_duplicate': bars.append(bars[-1])
    else: bars.append(_bar(20261025, 30.))
    _write_day(f['seed'], bars)
    _rebind_ipo_fixture(f)
    context = {'path': f['descriptorref']['path'], 'expected_sha256': f['descriptorref']['sha256']}
    assert sync._local_history_status(f['seed'], 20261024, seed_evidence=context, symbol=f['symbol'])[1] is not None
    assert context['records'][0]['status'] == 'EXPLAINED_IPO_FIRST_FIVE_SESSIONS' or problem == 'five_stock_bars_not_five_sessions'


@pytest.mark.parametrize('bad_field,new_bar_jump', [(True, False), (False, True)])
def test_ipo_history_keeps_original_field_and_new_provider_gates(tmp_path, monkeypatch, bad_field, new_bar_jump):
    import struct
    import ops.a_share_daily_sync as sync
    f = _ipo_fixture(tmp_path)
    if bad_field:
        raw = bytearray(f['seed'].read_bytes())
        struct.pack_into('<I', raw, 20, 0x00400000)
        struct.pack_into('<I', raw, 24, 0)
        f['seed'].write_bytes(raw)
    original = f['seed'].read_bytes()
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    calls = []
    scripts = {('h1', '601091'): [[_bar(20260924, 29.5), _bar(20261023, 90.)]]}
    result = sync.run_sync([sync.DailyTarget(code='601091', market=1, path=f['seed'])], target_date='20261023',
        api_factory=lambda host, _port: _FakeSession(host, scripts, calls), host_candidates=(('h1', 7709),),
        progress_path=tmp_path / 'progress.json', seed_adjustment_inputs=f['descriptorref']['path'],
        seed_adjustment_inputs_sha256=f['descriptorref']['sha256'])
    assert result['status'] == 'FAILED' and f['seed'].read_bytes() == original
    expected = sync.KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE if bad_field else sync.CROSS_DAY_CLOSE_RATIO
    assert result['by_symbol']['601091']['reason_code'] == expected
    assert calls == ([] if bad_field else [('h1', '601091')])
    assert result['seed_adjustment_evidence']['records'][0]['status'] == 'EXPLAINED_IPO_FIRST_FIVE_SESSIONS'


@pytest.mark.parametrize('pin', [None, '0' * 64, 'original_approved_pin'])
def test_ipo_history_external_pin_cannot_be_replaced_by_rehashed_chain(tmp_path, pin):
    import ops.a_share_daily_sync as sync
    f = _ipo_fixture(tmp_path)
    approved = f['descriptorref']['sha256']
    if pin == 'original_approved_pin':
        f['descriptor']['fixture_replacement'] = True
        _rebind_ipo_fixture(f)
        pin = approved
    context = {'path': f['descriptorref']['path'], 'expected_sha256': pin}
    original = f['seed'].read_bytes()
    assert sync._local_history_status(f['seed'], 20261024, seed_evidence=context, symbol=f['symbol'])[1] == sync.CROSS_DAY_CLOSE_RATIO
    assert context['records'][-1]['status'] == 'UNEXPLAINED'
    assert f['seed'].read_bytes() == original
