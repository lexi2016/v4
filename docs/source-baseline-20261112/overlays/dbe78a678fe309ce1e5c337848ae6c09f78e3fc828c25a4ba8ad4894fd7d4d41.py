from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import ops.macos_research_panel_daily as facade


ROOT = Path(__file__).resolve().parents[1]
PREIMAGE_COMMIT = "fdc34096bb3ebefe82ed1f8b90ee16e9c0727aaf"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _load_preimage(tmp_path: Path) -> ModuleType:
    source = subprocess.run(
        ["git", "show", f"{PREIMAGE_COMMIT}:ops/macos_research_panel_daily.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    source_path = tmp_path / "macos_research_panel_daily_preimage.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source)
    module_name = f"macos_research_panel_daily_preimage_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _a_rows(target_date: str) -> list[dict[str, Any]]:
    return [
        {
            "trade_date": target_date,
            "code": "000001.SZ",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 100,
            "turnover": 1234.5,
        },
        {
            "trade_date": target_date,
            "code": "600001.SH",
            "open": 20.0,
            "high": 21.0,
            "low": 19.5,
            "close": 20.5,
            "volume": 200,
            "turnover": 2345.5,
        },
    ]


def _hk_rows(target_date: str) -> list[dict[str, Any]]:
    return [
        {
            "trade_date": target_date,
            "code": "00001.HK",
            "open": 3.0,
            "high": 3.5,
            "low": 2.8,
            "close": 3.4,
            "volume": 1000,
            "turnover": 10000.0,
        },
        {
            "trade_date": target_date,
            "code": "00002.HK",
            "open": 4.0,
            "high": 4.5,
            "low": 3.8,
            "close": 4.4,
            "volume": 2000,
            "turnover": 20000.0,
        },
    ]


def _relative_result(result: dict[str, Any], root: Path) -> dict[str, Any]:
    value = json.loads(json.dumps(result))
    for item in value.get("files", []):
        if isinstance(item, dict) and "path" in item:
            item["path"] = str(Path(item["path"]).relative_to(root))
    return value


def test_dynamic_authority_module_supports_dataclass_and_remains_registered(
    tmp_path: Path,
) -> None:
    import ops.macos_research_panel_daily_authority as authority

    module_name = f"dynamic_authority_{id(tmp_path)}"
    script = tmp_path / "authority_dataclass.py"
    script.write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Result:\n"
        "    value: int\n"
        "RESULT = Result(7)\n",
        encoding="utf-8",
    )

    assert module_name not in sys.modules
    module = authority._load_authority_module(script, module_name)

    assert module.RESULT.value == 7
    assert sys.modules[module_name] is module

    sys.modules.pop(module_name, None)


def test_dynamic_authority_module_failure_removes_temporary_module(
    tmp_path: Path,
) -> None:
    import ops.macos_research_panel_daily_authority as authority

    module_name = f"dynamic_authority_failure_{id(tmp_path)}"
    script = tmp_path / "authority_failure.py"
    script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    assert module_name not in sys.modules
    with pytest.raises(RuntimeError, match="boom"):
        authority._load_authority_module(script, module_name)

    assert module_name not in sys.modules


def test_dynamic_authority_module_failure_restores_existing_module(
    tmp_path: Path,
) -> None:
    import ops.macos_research_panel_daily_authority as authority

    module_name = f"dynamic_authority_restore_{id(tmp_path)}"
    original = ModuleType(module_name)
    original.marker = "original"
    sys.modules[module_name] = original
    script = tmp_path / "authority_restore_failure.py"
    script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    try:
        with pytest.raises(RuntimeError, match="boom"):
            authority._load_authority_module(script, module_name)

        assert sys.modules[module_name] is original
        assert sys.modules[module_name].marker == "original"
    finally:
        sys.modules.pop(module_name, None)


def test_collectors_keep_exact_date_order_and_source_digest_with_offline_fakes(
    tmp_path: Path,
) -> None:
    preimage = _load_preimage(tmp_path / "preimage")

    class AClient:
        def connect(self, _host: str, _port: int) -> bool:
            return True

        def get_security_bars(self, _kind: int, _market: int, code: str, _start: int, _count: int):
            return [
                {
                    "datetime": "2026-08-19 15:00:00",
                    "open": 10.0 + int(code[-1]),
                    "high": 11.0 + int(code[-1]),
                    "low": 9.0 + int(code[-1]),
                    "close": 10.5 + int(code[-1]),
                    "vol": 12.0,
                    "amount": 345.0,
                }
            ]

        def disconnect(self) -> None:
            pass

    a_kwargs = {
        "universe_rows": [
            {"ts_code": "600001.SH"},
            {"ts_code": "000001.SZ"},
        ],
        "target_date": "20260819",
        "client_factory": AClient,
        "hq_hosts_override": [("fake", "127.0.0.1", 7709)],
    }
    assert preimage.collect_a_pytdx_rows(**a_kwargs) == facade.collect_a_pytdx_rows(**a_kwargs)

    class HKContext:
        def __init__(self) -> None:
            self.codes = [f"HK.{number:05d}" for number in range(1, 601)]

        def get_plate_stock(self, plate_code: str):
            items = self.codes if plate_code == "HK.GangGuTong" else []
            return 0, [{"code": code, "stock_name": code} for code in items]

        def get_market_snapshot(self, codes: list[str]):
            return 0, [
                {
                    "code": code,
                    "name": code,
                    "update_time": "2026-08-19 16:00:00",
                    "open_price": 10.0,
                    "high_price": 11.0,
                    "low_price": 9.0,
                    "last_price": 10.5,
                    "volume": 100.0,
                    "turnover": 1000.0,
                }
                for code in codes
            ]

        def close(self) -> None:
            pass

    hk_kwargs = {
        "target_date": "20260819",
        "context_factory": HKContext,
        "batch_size": 200,
        "minimum_universe_count": 600,
        "required_coverage_ratio": 1.0,
    }
    assert preimage.collect_hk_futu_rows(**hk_kwargs) == facade.collect_hk_futu_rows(**hk_kwargs)


def test_pack_preserves_a_hk_bytes_idempotency_and_history_guards(tmp_path: Path) -> None:
    preimage = _load_preimage(tmp_path / "preimage")
    old_a_root = tmp_path / "old-a"
    new_a_root = tmp_path / "new-a"
    old_hk_root = tmp_path / "old-hk"
    new_hk_root = tmp_path / "new-hk"

    old_a = preimage.pack_a_day(old_a_root, _a_rows("20260819"), target_date="20260819")
    new_a = facade.pack_a_day(new_a_root, _a_rows("20260819"), target_date="20260819")
    assert _relative_result(old_a, old_a_root) == _relative_result(new_a, new_a_root)
    for relative in ("vipdoc/sz/lday/sz000001.day", "vipdoc/sh/lday/sh600001.day"):
        assert (old_a_root / relative).read_bytes() == (new_a_root / relative).read_bytes()

    old_hk = preimage.pack_hk_day(old_hk_root, _hk_rows("20260819"), target_date="20260819", minimum_rows=1)
    new_hk = facade.pack_hk_day(new_hk_root, _hk_rows("20260819"), target_date="20260819", minimum_rows=1)
    assert _relative_result(old_hk, old_hk_root) == _relative_result(new_hk, new_hk_root)
    for relative in ("vipdoc/ds/lday/71#00001.day", "vipdoc/ds/lday/71#00002.day"):
        assert (old_hk_root / relative).read_bytes() == (new_hk_root / relative).read_bytes()

    assert facade.pack_a_day(new_a_root, _a_rows("20260819"), target_date="20260819")["files"][0]["already_current"] is True
    assert facade.pack_hk_day(new_hk_root, _hk_rows("20260819"), target_date="20260819", minimum_rows=1)["files"][0]["already_current"] is True
    with pytest.raises(facade.SnapshotGateError, match="target date is older"):
        facade.pack_a_day(new_a_root, _a_rows("20260818"), target_date="20260818")


def test_a_formula_already_current_binds_selector_and_backtest_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    import hashlib

    import ops.macos_research_panel_daily_authority as authority

    target_date = "20260819"
    selector = tmp_path / "selector.parquet"
    backtest = tmp_path / "backtest.parquet"
    selector.write_bytes(b"selector-artifact")
    backtest.write_bytes(b"backtest-artifact")
    selector_pointer = tmp_path / "selector.current"
    backtest_pointer = tmp_path / "backtest.current"
    selector_pointer.write_text(str(selector) + "\n", encoding="utf-8")
    backtest_pointer.write_text(str(backtest) + "\n", encoding="utf-8")
    monkeypatch.setattr(authority, "_parquet_max_date", lambda _path: int(target_date))

    result = authority.run_windows_a_formula_authority(
        tmp_path / "unused-formula.py",
        tdx_root=tmp_path / "tdx",
        data_root=tmp_path / "data",
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        selector_seed=None,
        backtest_seed=None,
        contract_csv=tmp_path / "contract.csv",
        canonical_formula_path=tmp_path / "formula.json",
        return_root=tmp_path / "returns",
        target_date=target_date,
    )

    selector_sha = hashlib.sha256(selector.read_bytes()).hexdigest()
    backtest_sha = hashlib.sha256(backtest.read_bytes()).hexdigest()
    expected_combined = hashlib.sha256(
        f"selector:{selector_sha}\nbacktest:{backtest_sha}\n".encode()
    ).hexdigest()
    assert result["already_current"] is True
    assert result["selector_sha256"] == selector_sha
    assert result["backtest_sha256"] == backtest_sha
    assert result["sha256"] == expected_combined


def test_authority_subprocess_and_lane_receipts_keep_seams_and_safety_flags(
    tmp_path: Path, monkeypatch
) -> None:
    seen: dict[str, Any] = {}

    class Completed:
        stdout = json.dumps({"status": "READY", "through_date": "20260819", "sha256": "h" * 64}) + "\n"

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(facade.subprocess, "run", fake_run)
    authority = facade.run_hk_0_2_authority(
        tmp_path / "update.py",
        tmp_path / "python3",
        tmp_path / "assets",
        tmp_path / "tdx",
        "20260819",
    )
    assert seen["kwargs"] == {"shell": False, "check": True, "capture_output": True, "text": True}
    assert seen["argv"] == [
        str(tmp_path / "python3"),
        str(tmp_path / "update.py"),
        "--asset-root",
        str(tmp_path / "assets"),
        "--tdx-root",
        str(tmp_path / "tdx"),
        "--through-date",
        "20260819",
    ]
    assert authority["argv"] == seen["argv"]
    assert authority["production_allowed"] is False
    assert authority["buy_gate_updated"] is False
    assert authority["orders_sent"] is False

    calls: list[str] = []
    result = facade.run_lanes(
        target_date="20260819",
        receipt_root=tmp_path / "receipts",
        a_runner=lambda target: calls.append(f"A:{target}") or {"status": "READY", "target_date": target},
        hk_runner=lambda target: calls.append(f"HK:{target}") or {"status": "READY", "target_date": target},
        lane="A",
    )
    assert calls == ["A:20260819"]
    assert result["overall_status"] == "READY"
    assert result["lanes"]["A"]["production_allowed"] is False
    assert result["lanes"]["HK"]["status"] == "NOT_REQUESTED"
    assert (tmp_path / "receipts" / "a-20260819.json").is_file()
    assert not (tmp_path / "receipts" / "hk-20260819.json").exists()


def test_hk_authority_reads_one_complete_payload_while_bounding_logs(
    tmp_path: Path, monkeypatch
) -> None:
    payload = {
        "status": "READY",
        "through_date": "20260819",
        "sha256": "h" * 64,
        "padding": "x" * 5000,
    }
    stdout = "updater started\n" + json.dumps(payload, sort_keys=True) + "\nupdater done\n"

    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self) -> None:
            self.stdout = stdout

    monkeypatch.setattr(facade.subprocess, "run", lambda *_args, **_kwargs: Completed())
    result = facade.run_hk_0_2_authority(
        tmp_path / "update.py",
        tmp_path / "python3",
        tmp_path / "assets",
        tmp_path / "tdx",
        "20260819",
    )

    assert result["status"] == "READY"
    assert result["through_date"] == "20260819"


def test_hk_authority_rejects_ambiguous_payload_lines(tmp_path: Path, monkeypatch) -> None:
    first = json.dumps({"status": "READY", "through_date": "20260819"})
    second = json.dumps({"status": "READY", "through_date": "20260819", "sha256": "h" * 64})

    class Completed:
        returncode = 0
        stdout = f"{first}\n{second}\n"
        stderr = ""

    monkeypatch.setattr(facade.subprocess, "run", lambda *_args, **_kwargs: Completed())
    with pytest.raises(facade.SnapshotGateError, match="ambiguous"):
        facade.run_hk_0_2_authority(
            tmp_path / "update.py",
            tmp_path / "python3",
            tmp_path / "assets",
            tmp_path / "tdx",
            "20260819",
        )


def test_hk_authority_rejects_duplicate_json_keys(tmp_path: Path, monkeypatch) -> None:
    class Completed:
        returncode = 0
        stdout = '{"status":"READY","through_date":"20260819","through_date":"20260819"}\n'
        stderr = ""

    monkeypatch.setattr(facade.subprocess, "run", lambda *_args, **_kwargs: Completed())
    with pytest.raises(facade.SnapshotGateError, match="not JSON"):
        facade.run_hk_0_2_authority(
            tmp_path / "update.py",
            tmp_path / "python3",
            tmp_path / "assets",
            tmp_path / "tdx",
            "20260819",
        )


def _main_a_argv(tmp_path: Path, target_date: str) -> list[str]:
    a_tdx_root = tmp_path / "a-tdx"
    (a_tdx_root / "vipdoc" / "sh" / "lday").mkdir(parents=True)
    (a_tdx_root / "vipdoc" / "sh" / "lday" / "sh600001.day").write_bytes(b"fixture")
    path_args = (
        ("--a-sync-script", "a-sync.py"),
        ("--a-formula-script", "a-formula.py"),
        ("--a-seed-panel", "a-seed.json"),
        ("--a-data-root", "a-data"),
        ("--a-selector-pointer", "selector.current"),
        ("--a-backtest-pointer", "backtest.current"),
        ("--a-selector-seed", "selector-seed.json"),
        ("--a-backtest-seed", "backtest-seed.json"),
        ("--a-contract-csv", "contract.csv"),
        ("--a-canonical-formula", "formula.json"),
        ("--a-return-root", "returns"),
        ("--hk-updater-script", "hk-update.py"),
        ("--hk-asset-root", "hk-assets"),
    )
    argv = [
        "macos_research_panel_daily.py",
        "--date",
        target_date,
        "--lane",
        "A",
        "--receipt-root",
        str(tmp_path / "receipts"),
        "--a-tdx-root",
        str(a_tdx_root),
        "--hk-tdx-root",
        str(tmp_path / "hk-tdx"),
    ]
    for option, name in path_args:
        argv.extend((option, str(tmp_path / name)))
    return argv


def test_a_formula_authority_rebuild_is_partial_and_explicit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target_date = "20260819"
    monkeypatch.setattr(
        facade,
        "run_windows_a_sync_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "authority_status": "PASS",
            "target_date": target_date,
            "accepted_target_date_file_count": 3,
            "target_date_file_count": 3,
            "coverage_rate": 1.0,
        },
    )
    monkeypatch.setattr(
        facade,
        "run_windows_a_formula_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "target_date": target_date,
            "coverage_rate": 1.0,
            "authority": {
                "authority_status": "REBUILD_REQUIRED",
                "selector_increment_rows": 7,
                "source_sha256": "a" * 64,
            },
        },
    )
    monkeypatch.setattr(sys, "argv", _main_a_argv(tmp_path, target_date))

    assert facade.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["overall_status"] == "PARTIAL"
    assert result["lanes"]["A"]["status"] == "PARTIAL"
    assert result["lanes"]["A"]["authority_status"] == "REBUILD_REQUIRED"
    assert "FORMULA_AUTHORITY_REBUILD_REQUIRED" in result["lanes"]["A"]["reason"]


def test_main_emits_compact_authority_envelope_and_keeps_large_receipt(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target_date = "20260819"
    receipt_root = tmp_path / "receipts"
    rows = [{"code": f"HK.{number:05d}", "trade_date": target_date} for number in range(652)]
    files = [{"path": str(tmp_path / f"71#{number:05d}.day")} for number in range(652)]
    outcome = {
        "status": "READY",
        "target_date": target_date,
        "row_count": len(rows),
        "coverage_rate": 1.0,
        "sha256": "a" * 64,
        "rows": rows,
        "files": files,
    }
    full_result = {
        "schema_version": "v3.macos.research_panel_daily.v1",
        "target_date": target_date,
        "requested_lane": "HK",
        "overall_status": "READY",
        "lanes": {"A": {"status": "NOT_REQUESTED"}, "HK": facade._receipt(receipt_root, "HK", target_date, outcome)},
        **facade.SAFETY_FLAGS,
    }
    monkeypatch.setattr(facade, "run_scheduled_lanes", lambda **_kwargs: full_result)
    argv = _main_a_argv(tmp_path, target_date)
    argv[argv.index("--lane") + 1] = "HK"
    monkeypatch.setattr(sys, "argv", argv)

    assert facade.main() == 0

    stdout = capsys.readouterr().out
    assert len(stdout) < 2048
    assert "\"rows\"" not in stdout
    assert "\"files\"" not in stdout
    envelope = json.loads(stdout)
    assert envelope["schema_version"] == "v3.macos.research_panel_authority_envelope.v1"
    assert envelope["overall_status"] == "READY"
    assert envelope["lane"] == "HK"
    assert envelope["lanes"]["HK"]["status"] == "READY"
    receipt = json.loads((receipt_root / "hk-20260819.json").read_text(encoding="utf-8"))
    assert len(receipt["rows"]) == 652
    assert len(receipt["files"]) == 652


def test_a_invalid_coverage_does_not_clamp_to_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target_date = "20260819"
    monkeypatch.setattr(
        facade,
        "run_windows_a_sync_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "authority_status": "PASS",
            "target_date": target_date,
            "accepted_target_date_file_count": 3,
            "target_date_file_count": 3,
            "coverage_rate": 1.0,
        },
    )
    monkeypatch.setattr(
        facade,
        "run_windows_a_formula_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "target_date": target_date,
            "coverage_rate": 2.0,
            "authority": {
                "authority_status": "PASS",
                "selector_increment_rows": 7,
                "source_sha256": "a" * 64,
            },
        },
    )
    monkeypatch.setattr(sys, "argv", _main_a_argv(tmp_path, target_date))

    assert facade.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["overall_status"] == "FAILED"
    assert result["lanes"]["A"]["status"] == "FAILED"
    assert "coverage_rate" in result["lanes"]["A"]["error"]


def test_a_bool_row_count_does_not_fallback_to_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target_date = "20260819"
    monkeypatch.setattr(
        facade,
        "run_windows_a_sync_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "authority_status": "PASS",
            "target_date": target_date,
            "accepted_target_date_file_count": 3,
            "target_date_file_count": 3,
            "coverage_rate": 1.0,
        },
    )
    monkeypatch.setattr(
        facade,
        "run_windows_a_formula_authority",
        lambda *_args, **_kwargs: {
            "status": "READY",
            "target_date": target_date,
            "coverage_rate": 1.0,
            "authority": {
                "authority_status": "PASS",
                "selector_increment_rows": True,
                "source_sha256": "a" * 64,
            },
        },
    )
    monkeypatch.setattr(sys, "argv", _main_a_argv(tmp_path, target_date))

    assert facade.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["overall_status"] == "FAILED"
    assert result["lanes"]["A"]["status"] == "FAILED"
    assert "row_count" in result["lanes"]["A"]["error"]


def test_scheduled_non_trading_and_after_1700_paths_remain_truthful(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(facade, "_today_shanghai", lambda: "20260822")
    monkeypatch.setattr(facade, "_scheduled_day_is_cross_market_trading_day", lambda _date: False)
    called: list[str] = []
    result = facade.run_scheduled_lanes(
        target_date=None,
        receipt_root=tmp_path / "non-trading",
        a_runner=lambda date: called.append(f"A:{date}") or {"status": "READY"},
        hk_runner=lambda date: called.append(f"HK:{date}") or {"status": "READY"},
    )
    assert result["overall_status"] == "NON_TRADING_DAY"
    assert called == []
    assert result["lanes"]["A"]["status"] == "NON_TRADING_DAY"
    assert result["lanes"]["HK"]["status"] == "NON_TRADING_DAY"

    monkeypatch.setattr(facade, "selector_pointer_is_ready", lambda *_args: False)
    after = facade.ensure_after_1700(
        target_date="20260819",
        receipt_root=tmp_path / "after",
        selector_pointer=tmp_path / "selector.current",
        a_runner=lambda target: {"status": "READY", "target_date": target, "row_count": 1},
        hk_runner=lambda target: {"status": "READY", "target_date": target, "row_count": 1},
        now=datetime(2026, 8, 19, 18, 0, tzinfo=SHANGHAI),
    )
    assert after["status"] == "ATTEMPTED"
    assert after["selector_pointer_ready"] is False
    assert facade.ensure_exit_code(after) == 2
    assert all(after[name] is False for name in facade.SAFETY_FLAGS)


def test_direct_script_help_matches_module_cli() -> None:
    script = ROOT / "ops" / "macos_research_panel_daily.py"
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    direct = subprocess.run(
        [sys.executable, "-B", str(script), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    module = subprocess.run(
        [sys.executable, "-B", "-m", "ops.macos_research_panel_daily", "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert module.returncode == 0, module.stderr
    assert direct.returncode == 0, direct.stderr
    assert direct.stdout.split("\n\n", 1)[1] == module.stdout.split("\n\n", 1)[1]
