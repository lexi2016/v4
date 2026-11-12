"""Contract tests for the isolated North Exchange PyTDX HQ collector."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.live_acquisition.pytdx_hq import (
    _PYTDX_HQ_PROBE,
    _parse_payload,
    collect_pytdx_hq_minute,
)

TRADE_DATE = "20260806"
MARKER = "__PYTDX_HQ_MINUTE_JSON__"


def raw_bar(time_key: str, *, code: str = "BJ.920275", close: float = 10.0) -> dict:
    return {
        "time_key": time_key,
        "code": code,
        "name": code,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 100.0,
        "turnover": 1000.0,
        "last_close": close - 0.2,
    }


def make_runner(payload: dict, *, returncode: int = 0):
    captured: dict = {}

    def runner(argv, *, input, capture_output, text, encoding, errors, timeout, shell):
        captured.update(
            argv=list(argv), input=input, capture_output=capture_output, text=text,
            encoding=encoding, errors=errors, timeout=timeout, shell=shell,
        )
        return SimpleNamespace(
            returncode=returncode,
            stdout=MARKER + json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    return runner, captured


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="v3sd_pytdx_hq_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.python = self.tmp / "python.exe"
        self.python.write_text("", encoding="utf-8")


class TestPytdxHqCollector(_Base):
    def test_probe_defines_marker_inside_child_process(self) -> None:
        self.assertIn('MARKER = "__PYTDX_HQ_MINUTE_JSON__"', _PYTDX_HQ_PROBE)

    def test_probe_uses_dynamic_pytdx_host_catalog(self) -> None:
        self.assertIn("from pytdx.config.hosts import hq_hosts", _PYTDX_HQ_PROBE)
        self.assertIn("for _name, host, port in hq_hosts[:80]", _PYTDX_HQ_PROBE)
        self.assertNotIn("119.147.212.81", _PYTDX_HQ_PROBE)

    def test_child_probe_preserves_six_digit_string_codes_for_history_request(self) -> None:
        # Exact child-process contract: the HQ API returns data only when the
        # security code remains a six-character string (int conversion yields
        # an empty response, notably for leading-zero SZ symbols).
        child_prelude = r'''
import sys
import types

class FakeTdxHqAPI:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, host, port, time_out=2.0):
        return True

    def disconnect(self):
        pass

    def get_history_minute_time_data(self, market, code, date):
        if not isinstance(code, str) or len(code) != 6:
            return []
        return [{"price": 10.0 + index / 100, "vol": index + 1}
                for index in range(120)]

pytdx_module = types.ModuleType("pytdx")
hq_module = types.ModuleType("pytdx.hq")
config_module = types.ModuleType("pytdx.config")
hosts_module = types.ModuleType("pytdx.config.hosts")
hq_module.TdxHq_API = FakeTdxHqAPI
hosts_module.hq_hosts = [("dynamic-test", "127.0.0.1", 7709)]
pytdx_module.hq = hq_module
pytdx_module.config = config_module
config_module.hosts = hosts_module
sys.modules["pytdx"] = pytdx_module
sys.modules["pytdx.hq"] = hq_module
sys.modules["pytdx.config"] = config_module
sys.modules["pytdx.config.hosts"] = hosts_module
exec(%r, globals(), globals())
''' % _PYTDX_HQ_PROBE
        payload = {
            "trade_date": TRADE_DATE,
            "stage_id": "STAGE_0930_0935",
            "codes": ["SH.600881", "SZ.001301", "BJ.920275"],
            "market_by_code": {
                "SH.600881": 1,
                "SZ.001301": 0,
                "BJ.920275": 2,
            },
        }
        completed = subprocess.run(
            [sys.executable, "-c", child_prelude],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = _parse_payload(completed.stdout)
        self.assertEqual(result["requested_code_count"], 3)
        self.assertEqual(result["completed_code_count"], 3)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["no_data_codes"], [])
        rows_by_code = {
            code: [row for row in result["raw_rows"] if row["code"] == code]
            for code in payload["codes"]
        }
        self.assertEqual({code: len(rows) for code, rows in rows_by_code.items()}, {
            "SH.600881": 120,
            "SZ.001301": 120,
            "BJ.920275": 120,
        })
        self.assertEqual(rows_by_code["SZ.001301"][0]["time_key"], "2026-08-06 09:31:00")
        first_sh = rows_by_code["SH.600881"][0]
        second_sh = rows_by_code["SH.600881"][1]
        self.assertEqual(first_sh["open"], first_sh["close"])
        self.assertEqual(first_sh["high"], first_sh["close"])
        self.assertEqual(first_sh["low"], first_sh["close"])
        self.assertEqual(second_sh["close"], 10.01)
        self.assertEqual(second_sh["open"], second_sh["close"])
        self.assertIsNone(first_sh["last_close"])

        def child_runner(_argv, **kwargs):
            return subprocess.run(
                [sys.executable, "-c", child_prelude], **kwargs
            )

        direct = collect_pytdx_hq_minute(
            sys.executable,
            TRADE_DATE,
            "STAGE_0930_0935",
            payload["codes"],
            process_runner=child_runner,
        )
        self.assertEqual(direct.status, "READ_OK")
        self.assertEqual([row["code"] for row in direct.rows], payload["codes"])
        self.assertEqual(direct.rows[0]["open_price"], 10.0)
        self.assertEqual(direct.rows[0]["high_price"], 10.04)
        self.assertEqual(direct.rows[0]["low_price"], 10.0)
        self.assertEqual(direct.rows[0]["last_price"], 10.04)
        self.assertEqual(direct.rows[0]["bar_count"], 5)

    def test_mixed_a_share_codes_carry_authoritative_pytdx_market_mapping(self) -> None:
        payload = {
            "raw_rows": [
                raw_bar("2026-08-06 09:31:00", code="SH.600036", close=10.0),
                raw_bar("2026-08-06 09:31:00", code="SZ.000429", close=11.0),
                raw_bar("2026-08-06 09:31:00", code="BJ.920275", close=12.0),
            ],
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": 3,
            "completed_code_count": 3,
            "source_host": "test:7709",
        }
        runner, captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0930_0935",
            ["SH.600036", "SZ.000429", "BJ.920275"], process_runner=runner,
        )
        self.assertEqual(result.status, "READ_OK")
        self.assertEqual([row["code"] for row in result.rows], [
            "SH.600036", "SZ.000429", "BJ.920275",
        ])
        request = json.loads(captured["input"])
        self.assertEqual(request["market_by_code"], {
            "SH.600036": 1, "SZ.000429": 0, "BJ.920275": 2,
        })

    def test_no_datetime_history_rows_bind_to_fixed_morning_minutes(self) -> None:
        # PyTDX HQ's history-minute response carries only price/vol.  This
        # simulates the probe's code-tagged rows before deterministic time
        # binding; 120 rows are the completed 09:31-11:30 morning sequence.
        raw_rows = [
            {
                "code": "BJ.920275",
                "name": "BJ.920275",
                "open": 10.0 + index / 100,
                "high": 10.1 + index / 100,
                "low": 9.9 + index / 100,
                "close": 10.0 + index / 100,
                "volume": 1.0,
                "turnover": 10.0,
                "last_close": 9.9,
            }
            for index in range(120)
        ]
        payload = {
            "raw_rows": raw_rows,
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": 1,
            "completed_code_count": 1,
            "source_host": "test:7709",
        }
        runner, _captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0945_1030", ["BJ.920275"],
            process_runner=runner,
        )
        self.assertEqual(result.status, "READ_OK")
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["window_start"], "2026-08-06 09:46:00")
        self.assertEqual(result.rows[0]["window_end"], "2026-08-06 10:29:00")
        self.assertEqual(result.rows[0]["bar_count"], 44)

    def test_unstamped_history_rows_over_fixed_day_are_fail_closed(self) -> None:
        raw_rows = [
            {
                "code": "BJ.920275",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1.0,
                "turnover": 10.0,
                "last_close": 9.9,
            }
            for _ in range(241)
        ]
        payload = {
            "raw_rows": raw_rows,
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": 1,
            "completed_code_count": 1,
        }
        runner, _captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0930_0935", ["BJ.920275"],
            process_runner=runner,
        )
        self.assertEqual(result.status, "READ_FAILED")
        self.assertTrue(result.cannot_confirm)

    def test_bj_history_probe_uses_market_two_and_preserves_exact_window(self) -> None:
        payload = {
            "raw_rows": [raw_bar("2026-08-06 09:31:00")],
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": 1,
            "completed_code_count": 1,
            "source_host": "test:7709",
        }
        runner, captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0930_0935", ["BJ.920275"],
            process_runner=runner,
        )
        self.assertEqual(result.status, "READ_OK")
        self.assertEqual(result.rows[0]["code"], "BJ.920275")
        request = json.loads(captured["input"])
        self.assertEqual(request["trade_date"], TRADE_DATE)
        self.assertEqual(request["stage_id"], "STAGE_0930_0935")
        self.assertEqual(request["codes"], ["BJ.920275"])
        self.assertEqual(request["market_by_code"], {"BJ.920275": 2})
        self.assertEqual(captured["argv"][0], str(self.python))
        self.assertEqual(captured["argv"][1], "-c")
        self.assertIn("get_history_minute_time_data", captured["argv"][2])
        self.assertIn("market", captured["argv"][2])
        self.assertIn("trade_date", captured["argv"][2])
        self.assertFalse(captured["shell"])

    def test_non_a_share_symbols_are_rejected_before_probe(self) -> None:
        called: list[bool] = []

        def runner(**_kwargs):
            called.append(True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with self.assertRaises(ValueError):
            collect_pytdx_hq_minute(
                self.python, TRADE_DATE, "STAGE_0930_0935", ["HK.00001"],
                process_runner=runner,
            )
        self.assertEqual(called, [])

    def test_wrong_date_or_missing_window_is_fail_closed(self) -> None:
        payload = {
            "raw_rows": [raw_bar("2026-08-07 09:31:00")],
            "errors": [],
            "no_data_codes": [],
            "requested_code_count": 1,
            "completed_code_count": 1,
        }
        runner, _captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0930_0935", ["BJ.920275"],
            process_runner=runner,
        )
        self.assertEqual(result.status, "READ_FAILED")
        self.assertEqual(result.rows, [])
        self.assertEqual(result.no_data_codes, ["BJ.920275"])
        self.assertTrue(result.cannot_confirm)

    def test_no_data_is_typed_without_synthesizing_a_row(self) -> None:
        payload = {
            "raw_rows": [],
            "errors": [{"code": "BJ.920275", "error": "no bars"}],
            "no_data_codes": ["BJ.920275"],
            "requested_code_count": 1,
            "completed_code_count": 0,
        }
        runner, _captured = make_runner(payload)
        result = collect_pytdx_hq_minute(
            self.python, TRADE_DATE, "STAGE_0930_0935", ["BJ.920275"],
            process_runner=runner,
        )
        self.assertEqual(result.status, "READ_FAILED")
        self.assertEqual(result.no_data_codes, ["BJ.920275"])
        self.assertEqual(result.rows, [])


if __name__ == "__main__":
    unittest.main()
