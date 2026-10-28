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
