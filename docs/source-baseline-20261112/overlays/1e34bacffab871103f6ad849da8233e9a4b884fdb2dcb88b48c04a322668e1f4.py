from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "a_share_daily_sync.py"
spec = importlib.util.spec_from_file_location("current_day_sync", MODULE_PATH)
assert spec is not None and spec.loader is not None
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


def bar(date_value: int, close: float, *, amount: float = 1000.0, vol: float = 100.0) -> dict[str, Any]:
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


def write_bars(path: Path, *bars: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(sync.pack_hq_bar(item) for item in bars))


class ScriptedSession:
    def __init__(self, host: str, scripts: dict[tuple[str, str], list[Any]], calls: list[tuple[str, str]]) -> None:
        self.host = host
        self.scripts = scripts
        self.calls = calls

    def connect(self, host: str, _port: int, time_out: float | None = None) -> bool:
        assert host == self.host
        return True

    def get_security_bars(self, _kind: int, _market: int, code: str, _start: int, _count: int) -> Any:
        self.calls.append((self.host, code))
        return self.scripts.setdefault((self.host, code), [[]]).pop(0)

    def disconnect(self) -> None:
        return None


class EmptyResponseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_run_dir = sync.RUN_DIR

    def tearDown(self) -> None:
        sync.RUN_DIR = self._old_run_dir

    def _fixture(self, root: Path, code: str = "000001") -> tuple[sync.DailyTarget, Path]:
        native = root / f"sz{code}.day"
        write_bars(native, bar(20260907, 10.0))
        return sync.DailyTarget(code=code, market=0, path=native), native

    def _run(
        self,
        root: Path,
        targets: list[sync.DailyTarget],
        scripts: dict[tuple[str, str], list[Any]],
        calls: list[tuple[str, str]],
        *,
        progress: Path | None = None,
        hosts: tuple[tuple[str, int], ...] = (("h1", 7709), ("h2", 7709)),
        run_budget_seconds: float = 5.0,
    ) -> dict[str, Any]:
        sync.RUN_DIR = root / "run"
        return sync.run_sync(
            targets,
            target_date="20260908",
            api_factory=lambda host, _port: ScriptedSession(host, scripts, calls),
            host_candidates=hosts,
            progress_path=progress or root / "progress.json",
            request_deadline_seconds=0.5,
            symbol_budget_seconds=2.0,
            run_budget_seconds=run_budget_seconds,
        )

    def test_empty_rotates_to_next_host_and_accepts_valid_target(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            target, native = self._fixture(root)
            before = hashlib.sha256(native.read_bytes()).hexdigest()
            calls: list[tuple[str, str]] = []
            result = self._run(
                root,
                [target],
                {("h1", "000001"): [[]], ("h2", "000001"): [[bar(20260908, 10.2)]]},
                calls,
            )

            row = result["by_symbol"]["000001"]
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["accepted_count"], 1)
            self.assertEqual(calls, [("h1", "000001"), ("h2", "000001")])
            self.assertEqual(row["host"], "h2:7709")
            self.assertEqual(row["attempt_ordinal"], 2)
            self.assertEqual(len(row["raw_response_snapshots"]), 2)
            self.assertEqual(row["raw_response_snapshots"][0]["host"], "h1:7709")
            self.assertEqual(row["raw_response_snapshots"][1]["host"], "h2:7709")
            first_payload = json.loads(Path(row["raw_response_snapshots"][0]["path"]).read_text())
            self.assertEqual(first_payload["response_rows"], [])
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest() != before, True)
            self.assertEqual(sync.read_last_date(native), 20260908)
            self.assertEqual(result["pending_count"], 0)
            self.assertEqual(result["accepted_count"] + result["quarantine_count"] + result["pending_count"], 1)

    def test_all_hosts_empty_quarantines_after_bounded_rotation(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            target, native = self._fixture(root)
            before = hashlib.sha256(native.read_bytes()).hexdigest()
            calls: list[tuple[str, str]] = []
            result = self._run(
                root,
                [target],
                {("h1", "000001"): [[]], ("h2", "000001"): [[]]},
                calls,
            )

            row = result["by_symbol"]["000001"]
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["quarantine_count"], 1)
            self.assertEqual(result["pending_count"], 0)
            self.assertEqual(row["reason_code"], sync.EMPTY_RESPONSE)
            self.assertEqual(row["host"], "h2:7709")
            self.assertEqual(calls, [("h1", "000001"), ("h2", "000001")])
            self.assertEqual(len(row["raw_response_snapshots"]), 2)
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(), before)
            saved = json.loads((root / "progress.json").read_text())
            self.assertEqual(len(saved["symbol_progress"]["000001"]["raw_response_snapshots"]), 2)
            self.assertEqual(saved["failed_hosts"], [])

    def test_retained_empty_quarantine_reopens_and_keeps_prior_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            target, native = self._fixture(root)
            progress = root / "progress.json"
            first_calls: list[tuple[str, str]] = []
            first = self._run(
                root / "first",
                [target],
                {("h1", "000001"): [[]], ("h2", "000001"): [[]]},
                first_calls,
                progress=progress,
            )
            self.assertEqual(first["by_symbol"]["000001"]["reason_code"], sync.EMPTY_RESPONSE)
            self.assertEqual(len(first["by_symbol"]["000001"]["raw_response_snapshots"]), 2)

            second_calls: list[tuple[str, str]] = []
            second = self._run(
                root / "second",
                [target],
                {("h1", "000001"): [[bar(20260908, 10.2)]]},
                second_calls,
                progress=progress,
                hosts=(("h1", 7709), ("h2", 7709)),
            )
            row = second["by_symbol"]["000001"]
            self.assertEqual(second["status"], "PASS")
            self.assertEqual(second_calls, [("h1", "000001")])
            self.assertEqual(row["status"], "UPDATED")
            self.assertEqual(row["attempt_ordinal"], 1)
            self.assertEqual(len(row["raw_response_snapshots"]), 3)
            self.assertEqual([item["host"] for item in row["raw_response_snapshots"][:2]], ["h1:7709", "h2:7709"])
            self.assertEqual(row["raw_response_snapshots"][2]["host"], "h1:7709")
            self.assertEqual(sync.read_last_date(native), 20260908)
            self.assertEqual([sync.day_int(item) for item in sync.read_hq_day_bars(native)], [20260907, 20260908])

    def test_malformed_and_ratio_content_failures_do_not_rotate(self) -> None:
        known_amount = struct.unpack("<f", struct.pack("<I", sync.KNOWN_MALFORMED_AMOUNT_BITS))[0]
        cases = (
            ("600696", [bar(20260908, 10.2, amount=known_amount, vol=0.0)], sync.KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE),
            ("603388", [bar(20260908, 20.0)], sync.CROSS_DAY_CLOSE_RATIO),
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            for code, response, reason in cases:
                target, native = self._fixture(root / code, code)
                calls: list[tuple[str, str]] = []
                result = self._run(
                    root / code,
                    [target],
                    {("h1", code): [response]},
                    calls,
                )
                row = result["by_symbol"][code]
                self.assertEqual(row["reason_code"], reason)
                self.assertEqual(calls, [("h1", code)])
                self.assertEqual(len(row["raw_response_snapshots"]), 1)
                self.assertEqual(sync.read_last_date(native), 20260907)

    def test_accepted_current_control_does_not_call_provider(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            native = root / "sz301336.day"
            write_bars(native, bar(20260908, 10.2))
            target = sync.DailyTarget(code="301336", market=0, path=native)
            before = hashlib.sha256(native.read_bytes()).hexdigest()

            def fail_provider(*_args: Any) -> Any:
                raise AssertionError("accepted current control must not call provider")

            sync.RUN_DIR = root / "run"
            result = sync.run_sync(
                [target],
                target_date="20260908",
                api_factory=fail_provider,
                host_candidates=(("h1", 7709),),
                progress_path=root / "progress.json",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["by_symbol"]["301336"]["status"], "ALREADY_CURRENT")
            self.assertEqual(result["by_symbol"]["301336"]["raw_response_snapshots"], [])
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(), before)

    def test_run_budget_exhaustion_leaves_unprocessed_target(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            target, _native = self._fixture(root)
            calls: list[tuple[str, str]] = []
            result = self._run(
                root,
                [target],
                {("h1", "000001"): [[bar(20260908, 10.2)]]},
                calls,
                run_budget_seconds=0.000001,
            )
            self.assertEqual(result["status"], "TIMEOUT")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["quarantine_count"], 0)
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(calls, [])
            self.assertEqual(result["accepted_count"] + result["quarantine_count"] + result["pending_count"], 1)

    def test_duplicate_target_scope_rejected_before_provider(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            root = Path(temp).resolve()
            target, _native = self._fixture(root)
            calls: list[tuple[str, str]] = []
            with self.assertRaisesRegex(ValueError, "A_SYNC_TARGET_SCOPE_DUPLICATE"):
                self._run(root, [target, target], {}, calls)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
