from __future__ import annotations

import hashlib
import json
import struct
import threading
import time
from pathlib import Path

import pytest


def _bar(
    date_value: int,
    close: float,
    *,
    amount: float = 1000.0,
    vol: float = 100.0,
) -> dict[str, object]:
    return {
        "year": date_value // 10000,
        "month": date_value // 100 % 100,
        "day": date_value % 100,
        "open": close - 0.2,
        "high": close + 0.2,
        "low": close - 0.4,
        "close": close,
        "amount": amount,
        "vol": vol,
    }


def _write_day(path: Path, date_value: int, close: float = 10.0) -> None:
    from ops.a_share_daily_sync import pack_hq_bar

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_hq_bar(_bar(date_value, close)))


def _write_bars(path: Path, *bars: dict[str, object]) -> None:
    from ops.a_share_daily_sync import pack_hq_bar

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(pack_hq_bar(bar) for bar in bars))


def _known_signature_amount() -> float:
    return struct.unpack("<f", struct.pack("<I", 0x00400000))[0]


class _Session:
    def __init__(self, host: str, scripts: dict[tuple[str, str], list[object]], calls: list[tuple[str, str]]) -> None:
        self.host = host
        self.scripts = scripts
        self.calls = calls

    def connect(self, host: str, _port: int, time_out: float | None = None) -> bool:
        assert host == self.host
        return True

    def get_security_bars(self, _kind: int, _market: int, code: str, _start: int, _count: int):
        self.calls.append((self.host, code))
        value = self.scripts.setdefault((self.host, code), []).pop(0)
        if value == "interrupt":
            raise KeyboardInterrupt()
        if isinstance(value, tuple) and value and value[0] == "sleep":
            time.sleep(float(value[1]))
            return value[2]
        return value

    def disconnect(self) -> None:
        return None


def _target(tmp_path: Path, code: str) -> object:
    from ops.a_share_daily_sync import DailyTarget

    path = tmp_path / f"{code}.day"
    _write_day(path, 20260906)
    return DailyTarget(code=code, market=0, path=path)


def _seed_resume_progress(
    path: Path,
    targets: list[object],
    *,
    quarantined: tuple[str, ...] = (),
    pending: tuple[str, ...] = (),
    completed: tuple[str, ...] = (),
) -> None:
    from ops.a_share_daily_sync import _new_progress

    progress = _new_progress(20260907, targets, dry_run=False)
    progress["completed_symbols"] = list(completed)
    progress["pending_symbols"] = list(pending)
    for symbol in quarantined:
        progress["symbol_progress"][symbol] = {
            "symbol": symbol,
            "target_date": "20260907",
            "event": "CONTENT_FAILURE",
            "failure_type": "EMPTY_RESPONSE",
            "host": "h1:7709",
            "attempt_ordinal": 1,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def test_exact_date_progress_skips_accepted_symbol_on_restart(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000001")
    progress = tmp_path / "receipt" / "progress.json"
    calls: list[tuple[str, str]] = []
    scripts = {("h1", "000001"): [[_bar(20260907, 10.2)]]}
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, scripts, calls),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["status"] == "PASS"
    assert calls == [("h1", "000001")]
    saved = json.loads(progress.read_text(encoding="utf-8"))
    assert saved["target_date"] == "20260907"
    assert saved["completed_symbols"] == ["000001"]

    def should_not_fetch(*_args):
        raise AssertionError("accepted exact-date symbol was fetched again")

    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=should_not_fetch,
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert second["status"] == "PASS"
    assert second["by_symbol"]["000001"]["status"] == "ALREADY_CURRENT"
    assert calls == [("h1", "000001")]


def test_connect_failure_is_quarantined_and_not_retried_for_next_symbol(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    targets = [_target(tmp_path, code) for code in ("000001", "000002")]
    calls: list[tuple[str, str]] = []
    connects: list[str] = []
    scripts = {
        ("h2", "000001"): [[_bar(20260907, 10.2)]],
        ("h2", "000002"): [[_bar(20260907, 10.3)]],
    }

    class Session(_Session):
        def connect(self, host: str, _port: int, time_out: float | None = None) -> bool:
            connects.append(host)
            if host == "h1":
                raise OSError("endpoint unavailable")
            return super().connect(host, _port, time_out)

    result = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: Session(host, scripts, calls),
        host_candidates=(("h1", 7709), ("h2", 7709)),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "PASS"
    assert connects == ["h1", "h2"]
    assert calls == [("h2", "000001"), ("h2", "000002")]
    assert result["progress"]["failed_hosts"] == ["h1:7709"]


def test_native_run_sync_output_closes_through_authority_with_healthy_failover(
    tmp_path: Path,
) -> None:
    """Exercise the real run_sync report through the original authority seam."""
    from ops.macos_research_panel_daily import run_windows_a_sync_authority

    root = tmp_path / "tdx"
    for code in ("600000", "600001"):
        _write_day(root / "vipdoc" / "sh" / "lday" / f"sh{code}.day", 20260906)
    script = tmp_path / "native-run-sync-authority.py"
    script.write_text(
        """from pathlib import Path
from ops.a_share_daily_sync import (
    DailyTarget,
    _local_history_status,
    pack_hq_bar,
    run_sync,
    write_csv,
)

RUN_DIR = None

def _bar(close):
    return {
        'year': 2026, 'month': 9, 'day': 7,
        'open': close - 0.2, 'high': close + 0.2,
        'low': close - 0.4, 'close': close,
        'amount': 1000.0, 'vol': 100.0,
    }

class _Provider:
    def __init__(self, host):
        self.host = host

    def connect(self, host, _port, time_out=None):
        if host == 'bad':
            raise OSError('isolated endpoint failure')
        return True

    def get_security_bars(self, _kind, _market, code, _start, _count):
        if code == '600000':
            return [_bar(10.2)]
        return []

    def disconnect(self):
        return None

def run(args):
    root = Path(args.tdx_root)
    targets = [
        DailyTarget(code, 1, root / 'vipdoc' / 'sh' / 'lday' / f'sh{code}.day')
        for code in ('600000', '600001')
    ]
    result = run_sync(
        targets,
        target_date=str(args.target_date),
        api_factory=lambda host, _port: _Provider(host),
        host_candidates=(('bad', 7709), ('good', 7709)),
        count=20,
        timeout=1.0,
        progress_path=Path(RUN_DIR) / 'progress.json',
        request_deadline_seconds=0.5,
        symbol_budget_seconds=0.5,
        run_budget_seconds=5.0,
    )
    result['run_dir'] = str(RUN_DIR)
    write_csv(Path(RUN_DIR) / 'file_results.csv', list(result['by_symbol'].values()))
    return result
""",
        encoding="utf-8",
    )
    result = run_windows_a_sync_authority(
        script,
        root,
        "20260907",
        tmp_path / "receipt",
        minimum_target_date_files=1,
    )
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["accepted_count"] == 1
    assert result["quarantine_count"] == 1
    assert result["authority"]["status"] == "FAILED"
    assert result["authority"]["progress"]["failed_hosts"] == ["bad:7709"]
    assert result["formula_input_mode"] == "ACCEPTED_ONLY"
    manifest = json.loads(Path(result["formula_input_manifest"]).read_text(encoding="utf-8"))
    assert [Path(item["path"]).name for item in manifest["files"]] == ["sh600000.day"]


def test_failed_host_quarantine_is_run_scoped_and_revalidates_on_retry(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000009")
    progress = tmp_path / "receipt" / "progress.json"
    first_connects: list[str] = []

    class OutageSession(_Session):
        def connect(self, host: str, _port: int, time_out: float | None = None) -> bool:
            first_connects.append(host)
            raise OSError("temporary endpoint outage")

    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: OutageSession(host, {}, []),
        host_candidates=(("h1", 7709), ("h2", 7709)),
        progress_path=progress,
    )
    assert first["status"] == "FAILED"
    assert first_connects == ["h1", "h2"]
    assert first["progress"]["failed_hosts"] == ["h1:7709", "h2:7709"]

    retry_connects: list[str] = []
    retry_calls: list[tuple[str, str]] = []
    retry_scripts = {("h1", "000009"): [[_bar(20260907, 10.9)]]}

    class HealthySession(_Session):
        def connect(self, host: str, port: int, time_out: float | None = None) -> bool:
            retry_connects.append(host)
            return super().connect(host, port, time_out)

    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: HealthySession(host, retry_scripts, retry_calls),
        host_candidates=(("h1", 7709), ("h2", 7709)),
        progress_path=progress,
    )
    assert second["status"] == "PASS"
    assert retry_connects == ["h1"]
    assert retry_calls == [("h1", "000009")]
    # The durable progress still carries accepted exact-date work, while the
    # completed run no longer carries an old invocation's host quarantine.
    assert second["progress"]["failed_hosts"] == []
    assert second["by_symbol"]["000009"]["target_date_ready"] is True


def test_resume_services_exact_target_before_pending_retry_with_same_budget(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import pack_hq_bar, run_sync

    targets = [_target(tmp_path, code) for code in ("Q00001", "Q00002", "Q00003", "U00001", "U00002", "C00001")]
    current = targets[-1]
    current.path.write_bytes(pack_hq_bar(_bar(20260907, 11.1)))
    progress = tmp_path / "receipt" / "progress.json"
    _seed_resume_progress(
        progress,
        targets,
        quarantined=("Q00001", "Q00002", "Q00003"),
        pending=("U00001", "U00002"),
    )
    seeded_fingerprint = json.loads(progress.read_text(encoding="utf-8"))["target_fingerprint"]
    calls: list[tuple[str, str]] = []
    scripts = {
        ("h1", "Q00001"): [("sleep", 0.10, [])],
        ("h1", "Q00002"): [("sleep", 0.10, [])],
        ("h1", "Q00003"): [("sleep", 0.10, [])],
        ("h1", "U00001"): [[_bar(20260907, 10.5)]],
        ("h1", "U00002"): [[_bar(20260907, 10.6)]],
    }
    result = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, scripts, calls),
        host_candidates=(("h1", 7709),),
        request_deadline_seconds=0.5,
        symbol_budget_seconds=0.5,
        run_budget_seconds=0.04,
        progress_path=progress,
    )

    assert calls[:1] == [("h1", "Q00001")]
    quarantine_calls = [code for _host, code in calls if code.startswith("Q")]
    assert quarantine_calls == ["Q00001"]
    assert result["by_symbol"]["C00001"]["classification"] == "ACCEPTED"
    assert result["by_symbol"]["C00001"]["status"] == "ALREADY_CURRENT"
    assert all(result["by_symbol"][code]["classification"] != "ACCEPTED" for code in ("Q00001", "Q00002", "Q00003", "U00001", "U00002"))
    assert result["target_count"] == 6
    assert result["target_date"] == "20260907"
    assert result["progress"]["target_fingerprint"] == seeded_fingerprint
    assert result["timeout"] is True
    assert result["authority_status"] == "CANNOT_CONFIRM"


def test_completed_progress_survives_pending_first_budget(tmp_path: Path) -> None:
    """An untouched prior completion must not become this run's pending row."""
    from ops.a_share_daily_sync import _new_progress, pack_hq_bar, run_sync

    completed = _target(tmp_path, "C00001")
    completed.path.write_bytes(pack_hq_bar(_bar(20260907, 10.1)))
    pending = _target(tmp_path, "U00001")
    progress = tmp_path / "receipt" / "progress.json"
    seeded = _new_progress(20260907, [completed, pending], dry_run=False)
    seeded["completed_symbols"] = ["C00001"]
    seeded["pending_symbols"] = ["U00001"]
    source_sha = hashlib.sha256(completed.path.read_bytes()).hexdigest()
    seeded["symbol_progress"]["C00001"] = {
        "symbol": "C00001",
        "target_date": "20260907",
        "status": "ALREADY_CURRENT",
        "fetch_status": "ALREADY_CURRENT",
        "classification": "ACCEPTED",
        "target_date_ready": True,
        "source_sha256_before": source_sha,
        "source_sha256_after": source_sha,
    }
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text(json.dumps(seeded), encoding="utf-8")
    calls: list[tuple[str, str]] = []
    scripts = {("h1", "U00001"): [("sleep", 0.12, [])]}

    result = run_sync(
        [completed, pending],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, scripts, calls),
        host_candidates=(("h1", 7709),),
        request_deadline_seconds=0.5,
        symbol_budget_seconds=0.5,
        run_budget_seconds=0.04,
        progress_path=progress,
    )

    saved = json.loads(progress.read_text(encoding="utf-8"))
    assert result["timeout"] is True
    assert calls == [("h1", "U00001")]
    assert saved["completed_symbols"] == ["C00001"]
    assert saved["pending_symbols"] == []
    assert saved["symbol_progress"]["C00001"]["classification"] == "ACCEPTED"
    assert saved["symbol_progress"]["U00001"]["classification"] == "QUARANTINED"
    assert saved["symbol_progress"]["U00001"]["reason_code"] == "A_SYNC_TIMEOUT"


def test_same_date_empty_quarantine_retries_until_date_or_source_changes(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000015")
    progress = tmp_path / "receipt" / "progress.json"
    first_calls: list[tuple[str, str]] = []
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, {("h1", "000015"): [[]]}, first_calls),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["by_symbol"]["000015"]["reason_code"] == "EMPTY_RESPONSE"
    assert first_calls == [("h1", "000015")]

    retry_calls: list[tuple[str, str]] = []
    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000015"): [[]]}, retry_calls
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert second["by_symbol"]["000015"]["reason_code"] == "EMPTY_RESPONSE"
    assert second["by_symbol"]["000015"]["classification"] == "QUARANTINED"
    assert retry_calls == [("h1", "000015")]

    reopened_calls: list[tuple[str, str]] = []
    reopened = run_sync(
        [target],
        target_date="20260908",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000015"): [[_bar(20260908, 10.2)]]}, reopened_calls
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress-20260908.json",
    )
    assert reopened["status"] == "PASS"
    assert reopened_calls == [("h1", "000015")]


@pytest.mark.parametrize(
    ("bad_response", "reason_code"),
    [
        ([_bar(20260907, 20.0)], "CROSS_DAY_CLOSE_RATIO"),
        ([], "EMPTY_RESPONSE"),
    ],
    ids=("cross-day-content", "empty-content"),
)
def test_content_failure_retries_empty_but_retains_terminal_ratio_without_host_rotation(
    tmp_path: Path, bad_response: list[dict[str, object]], reason_code: str
) -> None:
    from ops.a_share_daily_sync import run_sync

    bad_code, good_code = "000022", "000023"
    targets = [_target(tmp_path, bad_code), _target(tmp_path, good_code)]
    progress = tmp_path / "receipt" / "progress.json"
    calls: list[tuple[str, str]] = []

    class NativeSession:
        def __init__(self, host: str, call_log: list[tuple[str, str]] | None = None) -> None:
            self.host = host
            self.call_log = calls if call_log is None else call_log

        def connect(self, host: str, _port: int, time_out: float | None = None) -> bool:
            assert host == self.host
            return True

        def get_security_bars(self, _kind: int, _market: int, code: str, _start: int, _count: int):
            self.call_log.append((self.host, code))
            if code == bad_code:
                return bad_response
            return [_bar(20260907, 10.2)]

        def disconnect(self) -> None:
            return None

    first = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: NativeSession(host),
        host_candidates=(("h1", 7709), ("h2", 7709)),
        progress_path=progress,
    )

    assert first["status"] == "FAILED"
    assert first["authority_status"] == "REBUILD_REQUIRED"
    if reason_code == "EMPTY_RESPONSE":
        assert calls == [("h1", bad_code), ("h2", bad_code), ("h1", good_code)]
        expected_host = "h2:7709"
        expected_snapshot_count = 2
    else:
        assert calls == [("h1", bad_code), ("h1", good_code)]
        expected_host = "h1:7709"
        expected_snapshot_count = 1
    if reason_code != "EMPTY_RESPONSE":
        assert all(host != "h2" for host, _code in calls)
    assert first["accepted_count"] == 1
    assert first["quarantine_count"] == 1
    assert first["pending_count"] == 0
    assert (
        first["accepted_count"] + first["quarantine_count"] + first["pending_count"]
        == first["target_count"]
        == 2
    )

    quarantined = first["by_symbol"][bad_code]
    assert quarantined["classification"] == "QUARANTINED"
    assert quarantined["reason_code"] == reason_code
    assert quarantined["host"] == expected_host
    snapshots = quarantined["raw_response_snapshots"]
    assert len(snapshots) == expected_snapshot_count
    snapshot = snapshots[0]
    snapshot_path = Path(snapshot["path"])
    assert snapshot_path.is_file()
    raw_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert raw_payload["symbol"] == bad_code
    assert raw_payload["host"] == "h1:7709"
    assert raw_payload["response_rows"] == bad_response
    assert snapshot["capture_id"] == hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    saved = json.loads(progress.read_text(encoding="utf-8"))
    saved_entry = saved["symbol_progress"][bad_code]
    assert saved["target_date"] == "20260907"
    assert saved_entry["symbol"] == bad_code
    assert saved_entry["classification"] == "QUARANTINED"
    assert saved_entry["reason_code"] == reason_code
    assert saved_entry["raw_response_snapshots"] == snapshots

    if reason_code == "EMPTY_RESPONSE":
        retry_calls: list[tuple[str, str]] = []
        reused = run_sync(
            targets,
            target_date="20260907",
            api_factory=lambda host, _port: NativeSession(host, retry_calls),
            host_candidates=(("h1", 7709), ("h2", 7709)),
            progress_path=progress,
        )
        assert retry_calls == [("h1", bad_code), ("h2", bad_code)]
        assert reused["by_symbol"][good_code]["status"] == "ALREADY_CURRENT"
        assert "retained_quarantine" not in reused["by_symbol"][bad_code]
        assert reused["by_symbol"][bad_code]["reason_code"] == "EMPTY_RESPONSE"
    else:
        def should_not_fetch(*_args):
            raise AssertionError("same-date terminal content evidence must be reused")

        reused = run_sync(
            targets,
            target_date="20260907",
            api_factory=should_not_fetch,
            host_candidates=(("h1", 7709), ("h2", 7709)),
            progress_path=progress,
        )
    assert reused["accepted_count"] == 1
    assert reused["quarantine_count"] == 1
    assert reused["pending_count"] == 0
    assert (
        reused["accepted_count"] + reused["quarantine_count"] + reused["pending_count"]
        == reused["target_count"]
        == 2
    )
    assert reused["by_symbol"][bad_code]["reason_code"] == reason_code
    if reason_code == "EMPTY_RESPONSE":
        assert len(reused["by_symbol"][bad_code]["raw_response_snapshots"]) == expected_snapshot_count * 2
    else:
        assert reused["by_symbol"][bad_code]["retained_quarantine"] is True
        assert reused["by_symbol"][bad_code]["raw_response_snapshots"] == snapshots


def test_completed_source_hash_mismatch_revalidates_without_duplicate_target_bar(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import day_int, pack_hq_bar, read_hq_day_bars, run_sync

    target = _target(tmp_path, "000016")
    progress = tmp_path / "receipt" / "progress.json"
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000016"): [[_bar(20260907, 10.2)]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["status"] == "PASS"
    target.path.write_bytes(pack_hq_bar(_bar(20260907, 10.3)))
    calls: list[tuple[str, str]] = []
    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000016"): [[_bar(20260907, 10.3)]]}, calls
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert calls == [("h1", "000016")]
    assert second["by_symbol"]["000016"]["status"] == "REVALIDATED_CURRENT"
    assert [day_int(row) for row in read_hq_day_bars(target.path)] == [20260907]


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount", float("nan")), ("vol", None)],
)
def test_invalid_formula_required_fields_are_quarantined_without_append(
    tmp_path: Path, field: str, value: object
) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000017")
    original = target.path.read_bytes()
    invalid = _bar(20260907, 10.2)
    invalid[field] = value
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, {("h1", "000017"): [[invalid]]}, []),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["by_symbol"]["000017"]["reason_code"] == "INVALID_BAR"
    assert target.path.read_bytes() == original


def test_invalid_local_duplicate_history_is_quarantined_before_provider_call(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import pack_hq_bar, run_sync

    target = _target(tmp_path, "000018")
    target.path.write_bytes(pack_hq_bar(_bar(20260906, 10.0)) * 2)

    def should_not_fetch(*_args):
        raise AssertionError("duplicate local history must fail before provider call")

    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=should_not_fetch,
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["by_symbol"]["000018"]["reason_code"] == "DUPLICATE_DATE"


def test_completed_progress_does_not_skip_changed_source(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import pack_hq_bar, run_sync

    target = _target(tmp_path, "000011")
    progress = tmp_path / "receipt" / "progress.json"
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, {("h1", "000011"): [[_bar(20260907, 10.2)]]}, []),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["status"] == "PASS"
    assert first["progress"]["completed_symbols"] == ["000011"]

    # A durable completed marker does not authorize skipping a source whose
    # last date has moved backwards or otherwise changed after the run.
    target.path.write_bytes(pack_hq_bar(_bar(20260906, 9.8)))
    calls: list[tuple[str, str]] = []
    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, {("h1", "000011"): [[_bar(20260907, 10.3)]]}, calls),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert second["status"] == "PASS"
    assert calls == [("h1", "000011")]
    assert second["by_symbol"]["000011"]["classification"] == "ACCEPTED"
    assert second["by_symbol"]["000011"]["status"] == "UPDATED"


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ("{not-json", "A_SYNC_PROGRESS_UNREADABLE"),
        (json.dumps({"schema_version": "v3_5.a_share.tdx_progress.v1", "target_date": "20260906"}), "A_SYNC_PROGRESS_DATE_MISMATCH"),
    ],
)
def test_corrupt_or_stale_progress_fails_closed(tmp_path: Path, payload: str, expected_error: str) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000012")
    progress = tmp_path / "receipt" / "progress.json"
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text(payload, encoding="utf-8")
    with pytest.raises(RuntimeError, match=expected_error):
        run_sync(
            [target],
            target_date="20260907",
            api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("provider must not run")),
            host_candidates=(("h1", 7709),),
            progress_path=progress,
        )


def test_all_resolved_targets_keep_pass_without_provider_calls(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import pack_hq_bar, run_sync

    targets = [_target(tmp_path, code) for code in ("000013", "000014")]
    for target in targets:
        target.path.write_bytes(pack_hq_bar(_bar(20260907, 10.1)))
    progress = tmp_path / "receipt" / "progress.json"
    _seed_resume_progress(progress, targets, pending=("000013", "000014"))
    provider_calls: list[str] = []

    def no_provider(*_args):
        provider_calls.append("called")
        raise AssertionError("resolved targets must not call the provider")

    result = run_sync(
        targets,
        target_date="20260907",
        api_factory=no_provider,
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert result["status"] == "PASS"
    assert result["authority_status"] == "PASS"
    assert result["accepted_count"] == 2
    assert result["quarantine_count"] == 0
    assert result["pending_count"] == 0
    assert provider_calls == []


def test_request_deadline_is_typed_and_does_not_mutate_file(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000003")
    original = target.path.read_bytes()
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host,
            {("h1", "000003"): [("sleep", 0.15, [_bar(20260907, 10.2)])]},
            [],
        ),
        host_candidates=(("h1", 7709),),
        request_deadline_seconds=0.03,
        symbol_budget_seconds=0.08,
        run_budget_seconds=0.5,
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "FAILED"
    assert result["exit_code"] == 2
    assert result["by_symbol"]["000003"]["reason_code"] == "A_SYNC_TIMEOUT"
    assert result["failures"][0]["failure_type"].startswith("A_SYNC_TIMEOUT")
    assert target.path.read_bytes() == original


def test_symbol_timeout_does_not_quarantine_host_for_healthy_next_symbol(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    targets = [_target(tmp_path, code) for code in ("SLOW0001", "GOOD0002")]
    calls: list[tuple[str, str]] = []
    scripts = {
        ("h1", "SLOW0001"): [("sleep", 0.12, [_bar(20260907, 10.2)])],
        ("h1", "GOOD0002"): [[_bar(20260907, 10.3)]],
    }
    result = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, scripts, calls),
        host_candidates=(("h1", 7709),),
        request_deadline_seconds=0.5,
        symbol_budget_seconds=0.03,
        run_budget_seconds=0.5,
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    assert calls == [("h1", "SLOW0001"), ("h1", "GOOD0002")]
    assert result["by_symbol"]["SLOW0001"]["classification"] == "QUARANTINED"
    assert result["by_symbol"]["SLOW0001"]["failure_type"].startswith("A_SYNC_TIMEOUT:SYMBOL")
    assert result["by_symbol"]["GOOD0002"]["classification"] == "ACCEPTED"
    assert result["timeout"] is False
    assert result["timeout_scope"] == "SYMBOL"
    assert result["progress"]["failed_hosts"] == []


def test_run_deadline_returns_partial_cannot_confirm_and_pending_symbols(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    targets = [_target(tmp_path, code) for code in ("000004", "000005")]
    result = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host,
            {
                ("h1", "000004"): [("sleep", 0.2, [_bar(20260907, 10.4)])],
                ("h1", "000005"): [[_bar(20260907, 10.5)]],
            },
            [],
        ),
        host_candidates=(("h1", 7709),),
        request_deadline_seconds=0.5,
        symbol_budget_seconds=1.0,
        run_budget_seconds=0.04,
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "TIMEOUT"
    assert result["exit_code"] == 124
    assert result["authority_status"] == "CANNOT_CONFIRM"
    assert result["pending_count"] == 1
    assert result["by_symbol"]["000005"]["classification"] == "UNPROCESSED"
    assert result["timeout_scope"] == "RUN"


def test_interrupted_request_writes_partial_receipt_and_is_resumable(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync
    from ops.a_share_daily_sync import day_int, read_hq_day_bars

    targets = [_target(tmp_path, code) for code in ("000007", "000008")]
    progress = tmp_path / "receipt" / "progress.json"
    first_calls: list[tuple[str, str]] = []
    first = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host,
            {
                ("h1", "000007"): [[_bar(20260907, 10.7)]],
                ("h1", "000008"): ["interrupt"],
            },
            first_calls,
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["status"] == "INTERRUPTED"
    assert first["exit_code"] == 130
    assert first["interrupted"] is True
    assert first["by_symbol"]["000008"]["failure_type"] == "A_SYNC_INTERRUPTED"
    assert first["progress"]["completed_symbols"] == ["000007"]
    assert json.loads(progress.read_text(encoding="utf-8"))["last_event"]["event"] == "INTERRUPTED"

    second_calls: list[tuple[str, str]] = []
    second = run_sync(
        targets,
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host,
            {("h1", "000008"): [[_bar(20260907, 10.8)]]},
            second_calls,
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert second["status"] == "PASS"
    assert second_calls == [("h1", "000008")]
    assert second["progress"]["completed_symbols"] == ["000007", "000008"]
    for target in targets:
        dates = [day_int(row) for row in read_hq_day_bars(target.path)]
        assert dates == [20260906, 20260907]
        assert len(dates) == len(set(dates))


def test_worker_thread_deadline_fails_before_provider_call() -> None:
    from ops.a_share_daily_sync import SyncTimeoutError, _deadline_guard

    provider_calls: list[str] = []
    errors: list[SyncTimeoutError] = []

    def worker() -> None:
        try:
            with _deadline_guard(0.03, scope="REQUEST"):
                provider_calls.append("entered")
        except SyncTimeoutError as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert provider_calls == []
    assert len(errors) == 1
    assert errors[0].unsupported_context is True
    assert errors[0].scope == "REQUEST_UNSUPPORTED_CONTEXT"


@pytest.mark.parametrize(
    ("bars", "expected"),
    [
        ([_bar(20260908, 10.2)], "OUT_OF_SCOPE_AFTER_TARGET_DATE"),
        ([_bar(20260907, 10.2), _bar(20260907, 10.2)], "DUPLICATE_DATE"),
    ],
)
def test_future_or_duplicate_provider_rows_are_quarantined_without_append(
    tmp_path: Path, bars: list[dict[str, object]], expected: str
) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000006")
    original = target.path.read_bytes()
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, {("h1", "000006"): [bars]}, []),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "FAILED"
    assert result["by_symbol"]["000006"]["reason_code"] == expected
    assert target.path.read_bytes() == original


def test_provider_impossible_calendar_date_is_quarantined_before_append(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000019")
    original = target.path.read_bytes()
    invalid = _bar(20260800, 10.2)
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000019"): [[invalid, _bar(20260907, 10.2)]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "FAILED"
    assert result["by_symbol"]["000019"]["reason_code"] == "INVALID_BAR"
    assert target.path.read_bytes() == original


def test_broken_source_symlink_is_rejected_without_outside_write(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import DailyTarget, run_sync

    outside = tmp_path / "outside.day"
    linked = tmp_path / "000020.day"
    linked.symlink_to(outside)
    result = run_sync(
        [DailyTarget(code="000020", market=0, path=linked)],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000020"): [[_bar(20260907, 10.2)]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )
    assert result["status"] == "FAILED"
    assert result["by_symbol"]["000020"]["classification"] == "QUARANTINED"
    assert linked.is_symlink()
    assert not outside.exists()


def test_duplicate_target_scope_is_rejected_before_provider_call(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000021")
    with pytest.raises(ValueError, match="A_SYNC_TARGET_SCOPE_DUPLICATE"):
        run_sync(
            [target, target],
            target_date="20260907",
            api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("provider must not run")),
            host_candidates=(("h1", 7709),),
            progress_path=tmp_path / "receipt" / "progress.json",
        )


def test_old_same_sha_accepted_cache_rechecks_known_signature_locally(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import _new_progress, run_sync

    target = _target(tmp_path, "000001")
    _write_bars(
        target.path,
        _bar(20260906, 10.0),
        _bar(20260907, 10.2, amount=_known_signature_amount(), vol=0.0),
    )
    progress = tmp_path / "receipt" / "progress.json"
    source_sha = hashlib.sha256(target.path.read_bytes()).hexdigest()
    seeded = _new_progress(20260907, [target], dry_run=False)
    seeded["completed_symbols"] = ["000001"]
    # Deliberately omit the new field-rule identity to model the old cache.
    seeded["symbol_progress"]["000001"] = {
        "symbol": "000001",
        "target_date": "20260907",
        "status": "ACCEPTED",
        "classification": "ACCEPTED",
        "source_sha256_before": source_sha,
        "source_sha256_after": source_sha,
        "rule_id": "A-FI-SYNC-001",
        "rule_version": "1",
    }
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text(json.dumps(seeded), encoding="utf-8")
    calls: list[str] = []

    def should_not_fetch(*_args: object) -> None:
        calls.append("called")
        raise AssertionError("known malformed local history must not reach provider")

    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=should_not_fetch,
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )

    row = result["by_symbol"]["000001"]
    violation = row["field_violations"][0]
    assert row["classification"] == "QUARANTINED"
    assert row["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert calls == []
    assert violation["date"] == 20260907
    assert violation["row_index"] == 1
    assert violation["native_path"] == str(target.path)
    assert violation["native_file_sha256"] == source_sha
    assert violation["amount_bits"] == "0x00400000"
    assert violation["volume_raw_uint32"] == 0
    assert violation["field_rule_id"] == "A-FI-SYNC-001.FIELD_SIGNATURE"
    assert violation["field_rule_version"] == "1"
    saved = json.loads(progress.read_text(encoding="utf-8"))
    assert saved["field_rule_id"] == "A-FI-SYNC-001.FIELD_SIGNATURE"
    assert saved["field_rule_version"] == "1"
    assert result["accepted_count"] + result["quarantine_count"] + result["pending_count"] == 1


def test_known_signature_in_any_local_history_row_blocks_provider(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000002")
    _write_bars(
        target.path,
        _bar(20260906, 10.0, amount=_known_signature_amount(), vol=0.0),
        _bar(20260907, 10.2),
    )
    calls: list[str] = []

    def should_not_fetch(*_args: object) -> None:
        calls.append("called")
        raise AssertionError("full-history field guard must run before provider")

    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=should_not_fetch,
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    row = result["by_symbol"]["000002"]
    assert row["classification"] == "QUARANTINED"
    assert row["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert row["field_violations"][0]["date"] == 20260906
    assert calls == []
    assert result["pending_count"] == 0


def test_known_signature_provider_bar_is_quarantined_before_append(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000003")
    original = target.path.read_bytes()
    calls: list[str] = []
    malformed = _bar(20260907, 10.2, amount=_known_signature_amount(), vol=0.0)
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000003"): [[malformed]]}, [(host, "000003")]
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    row = result["by_symbol"]["000003"]
    assert row["classification"] == "QUARANTINED"
    assert row["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert target.path.read_bytes() == original
    assert row["field_violations"][0]["source_snapshot"]["capture_id"]
    assert Path(row["field_violations"][0]["source_snapshot"]["path"]).is_file()


def test_provider_field_violation_binds_source_snapshot_sha(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000022")
    malformed = _bar(20260907, 10.2, amount=_known_signature_amount(), vol=0.0)
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000022"): [[malformed]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    violation = result["by_symbol"]["000022"]["field_violations"][0]
    snapshot = violation["source_snapshot"]
    snapshot_path = Path(snapshot["path"])
    assert violation["source_file_sha256"] == snapshot["sha256"]
    assert violation["source_file_sha256"] == hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    assert violation["native_file_sha256"] is None


def test_known_signature_quarantine_continues_to_healthy_symbol(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    bad = _target(tmp_path, "000004")
    _write_bars(
        bad.path,
        _bar(20260906, 10.0, amount=_known_signature_amount(), vol=0.0),
        _bar(20260907, 10.2),
    )
    good = _target(tmp_path, "000005")
    calls: list[tuple[str, str]] = []
    scripts = {("h1", "000005"): [[_bar(20260907, 10.3)]]}
    result = run_sync(
        [bad, good],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(host, scripts, calls),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    assert calls == [("h1", "000005")]
    assert result["by_symbol"]["000004"]["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert result["by_symbol"]["000005"]["classification"] == "ACCEPTED"
    assert result["accepted_count"] == 1
    assert result["quarantine_count"] == 1
    assert result["pending_count"] == 0


def test_zero_amount_zero_volume_pair_is_not_known_signature(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000006")
    zero_pair = _bar(20260907, 10.2, amount=0.0, vol=0.0)
    result = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000006"): [[zero_pair]]}, []
        ),
        host_candidates=(("h1", 7709),),
        progress_path=tmp_path / "receipt" / "progress.json",
    )

    assert result["status"] == "PASS"
    assert result["by_symbol"]["000006"]["classification"] == "ACCEPTED"
    assert result["by_symbol"]["000006"]["reason_code"] is None


def test_current_rule_quarantine_reuses_and_changed_source_reopens(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000007")
    _write_bars(
        target.path,
        _bar(20260906, 10.0, amount=_known_signature_amount(), vol=0.0),
        _bar(20260907, 10.2),
    )
    progress = tmp_path / "receipt" / "progress.json"
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("local signature must stop first run")),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["by_symbol"]["000007"]["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"

    retained_calls: list[str] = []

    def should_not_fetch(*_args: object) -> None:
        retained_calls.append("called")
        raise AssertionError("current-rule same-source quarantine must be retained")

    retained = run_sync(
        [target],
        target_date="20260907",
        api_factory=should_not_fetch,
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert retained["by_symbol"]["000007"]["retained_quarantine"] is True
    assert retained_calls == []

    _write_day(target.path, 20260906, 10.0)
    reopened_calls: list[tuple[str, str]] = []
    reopened = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda host, _port: _Session(
            host, {("h1", "000007"): [[_bar(20260907, 10.2)]]}, reopened_calls
        ),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert reopened_calls == [("h1", "000007")]
    assert reopened["by_symbol"]["000007"]["classification"] == "ACCEPTED"
    assert reopened["by_symbol"]["000007"]["status"] == "UPDATED"


def test_changed_source_multidefect_retains_known_field_violation(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import run_sync

    target = _target(tmp_path, "000023")
    progress = tmp_path / "receipt" / "progress.json"
    malformed = _bar(20260906, 10.0, amount=_known_signature_amount(), vol=0.0)
    _write_bars(target.path, malformed, _bar(20260907, 10.2))
    first = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("provider called first")),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )
    assert first["by_symbol"]["000023"]["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"

    # Change the source while retaining the known signature and introduce a
    # duplicate date so both defects are present in the current scan.
    _write_bars(target.path, malformed, _bar(20260906, 10.1), _bar(20260907, 10.2))
    second = run_sync(
        [target],
        target_date="20260907",
        api_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("provider called second")),
        host_candidates=(("h1", 7709),),
        progress_path=progress,
    )

    row = second["by_symbol"]["000023"]
    assert row["classification"] == "QUARANTINED"
    assert row["reason_code"] == "DUPLICATE_DATE"
    assert row["source_sha256_before"] != first["by_symbol"]["000023"]["source_sha256_before"]
    assert len(row["field_violations"]) == 1
    assert row["field_violations"][0]["reason_code"] == "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
    assert row["field_violations"][0]["date"] == 20260906
