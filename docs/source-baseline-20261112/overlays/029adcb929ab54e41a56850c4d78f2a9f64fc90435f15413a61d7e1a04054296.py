from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


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


def test_rebuild_candidate_preserves_untouched_raw_records_and_reserved_bytes(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DAY_STRUCT, build_rebuild_candidate, pack_hq_bar

    source_path = tmp_path / "000008.day"
    candidate_path = tmp_path / "candidate" / "000008.day"
    source_rows = [_bar(20260721, 2.28), _bar(20260722, 2.28), _bar(20260723, 2.34)]
    source_bytes = bytearray(b"".join(pack_hq_bar(row) for row in source_rows))
    struct.pack_into("<I", source_bytes, 28, 0xAABBCCDD)
    struct.pack_into("<I", source_bytes, DAY_STRUCT.size + 28, 0x11223344)
    struct.pack_into("<I", source_bytes, 2 * DAY_STRUCT.size + 28, 0x55667788)
    source_path.write_bytes(source_bytes)

    replacement = _bar(20260722, 2.28)
    result = build_rebuild_candidate(
        source_path,
        [replacement],
        candidate_path,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_replacement_dates=[20260722],
        expected_replacement_sha256={
            20260722: hashlib.sha256(pack_hq_bar(replacement)).hexdigest(),
        },
    )
    candidate_bytes = candidate_path.read_bytes()

    assert result["source_record_count"] == result["candidate_record_count"] == 3
    assert result["changed_rows"] == [1]
    assert candidate_bytes[:DAY_STRUCT.size] == bytes(source_bytes[:DAY_STRUCT.size])
    assert candidate_bytes[2 * DAY_STRUCT.size :] == bytes(source_bytes[2 * DAY_STRUCT.size :])
    assert struct.unpack_from("<I", candidate_bytes, 28)[0] == 0xAABBCCDD
    assert struct.unpack_from("<I", candidate_bytes, 2 * DAY_STRUCT.size + 28)[0] == 0x55667788
    assert candidate_bytes[DAY_STRUCT.size : 2 * DAY_STRUCT.size] == pack_hq_bar(replacement)


def test_rebuild_candidate_keeps_append_compatibility_without_rewriting_source(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import build_rebuild_candidate, pack_hq_bar

    source_path = tmp_path / "000008.day"
    candidate_path = tmp_path / "candidate.day"
    source_rows = [_bar(20260721, 2.28), _bar(20260722, 2.28)]
    source_path.write_bytes(b"".join(pack_hq_bar(row) for row in source_rows))
    original = source_path.read_bytes()
    appended = _bar(20260723, 2.34)

    result = build_rebuild_candidate(source_path, [appended], candidate_path)

    assert result["replaced_dates"] == [20260723]
    assert result["source_record_count"] == 2
    assert result["candidate_record_count"] == 3
    assert candidate_path.read_bytes() == original + pack_hq_bar(appended)
    assert source_path.read_bytes() == original


def test_rebuild_candidate_rejects_duplicate_invalid_truncated_and_stale_inputs(tmp_path: Path) -> None:
    import pytest

    from ops.a_share_daily_sync import build_rebuild_candidate, pack_hq_bar

    source_path = tmp_path / "000008.day"
    candidate_path = tmp_path / "candidate.day"
    target = _bar(20260722, 2.28)
    source_path.write_bytes(pack_hq_bar(target))

    with pytest.raises(ValueError, match="REPLACEMENT_DUPLICATE_DATE"):
        build_rebuild_candidate(source_path, [target, dict(target)], candidate_path)

    source_path.write_bytes(pack_hq_bar(target) + pack_hq_bar(target))
    with pytest.raises(ValueError, match="SOURCE_DUPLICATE_DATE"):
        build_rebuild_candidate(source_path, [target], candidate_path)

    source_path.write_bytes(pack_hq_bar(target))

    invalid = dict(target)
    invalid["amount"] = -1.0
    with pytest.raises(ValueError, match="REPLACEMENT_REJECTED"):
        build_rebuild_candidate(source_path, [invalid], candidate_path)

    source_path.write_bytes(source_path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="SOURCE_FILE_SHAPE_REJECTED"):
        build_rebuild_candidate(source_path, [target], candidate_path)

    source_path.write_bytes(pack_hq_bar(target))
    with pytest.raises(ValueError, match="SOURCE_SHA_MISMATCH"):
        build_rebuild_candidate(source_path, [target], candidate_path, expected_source_sha256="0" * 64)

    with pytest.raises(OSError, match="SOURCE_CANDIDATE_PATH_COLLISION"):
        build_rebuild_candidate(source_path, [target], source_path)


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
    assert result["failures"] == [
        {
            "symbol": "000002",
            "host": "h2:7709",
            "failure_type": "target_date_missing",
        }
    ]


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
    assert result["failures"] == [
        {
            "symbol": "000002",
            "host": "h2:7709",
            "failure_type": "target_date_missing",
        }
    ]


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
        )
    )

    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
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
