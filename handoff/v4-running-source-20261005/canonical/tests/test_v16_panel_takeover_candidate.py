"""Candidate contract regressions. Mocked authorities below are NOT E2E evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
from ops import macos_research_panel_daily as panel

DATE = "20260911"
SHANGHAI = ZoneInfo("Asia/Shanghai")
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
A_KEYS = ("A_TDX_ROOT", "A_SYNC_SCRIPT", "A_FORMULA_SCRIPT", "A_SEED_PANEL", "A_DATA_ROOT",
          "A_SELECTOR_POINTER", "A_BACKTEST_POINTER", "A_SELECTOR_SEED", "A_BACKTEST_SEED",
          "A_CONTRACT_CSV", "A_CANONICAL_FORMULA", "A_RETURN_ROOT")
HK_KEYS = ("HK_TDX_ROOT", "HK_UPDATER_SCRIPT", "HK_PYTHON_EXECUTABLE", "HK_ASSET_ROOT")


def bindings(tmp_path, monkeypatch, lane):
    for name in tuple(os.environ):
        if name.startswith("V35_RESEARCH_PANEL_") or name == "V35_A_SYNC_HOST":
            monkeypatch.delenv(name)
    keys = ("RECEIPT_ROOT",) + (A_KEYS if lane == "A" else HK_KEYS)
    result = {key: str(tmp_path / key.lower()) for key in keys}
    for key, value in result.items():
        monkeypatch.setenv("V35_RESEARCH_PANEL_" + key, value)
    return result


def request(lane):
    return DispatchRequest(scheduled_date=DATE, business_date=DATE, target_date=DATE,
                           slot="1700" if lane == "A" else "1720", mode=DispatchMode.LIVE)


def workload(lane):
    ident = "research_panel_daily_" + lane.lower()
    return next(w for w in load_workload_catalog().workloads if w.workload_id == ident)


def compact_fixture(root, lane, *, mutate=None):
    receipt = {"schema_version": "v3.macos.research_panel_receipt.v1", "lane": lane,
               "target_date": DATE, "status": "READY", **FLAGS}
    if mutate:
        receipt.update(mutate)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(receipt).encode()
    (root / f"{lane.lower()}-{DATE}.json").write_bytes(raw)
    return {"schema_version": "v3.macos.research_panel_authority_envelope.v1",
            "target_date": DATE, "overall_status": "READY", "requested_lane": lane,
            "lanes": {lane: {"status": "READY", "receipt_sha256": hashlib.sha256(raw).hexdigest(),
                             "receipt_bytes": len(raw)}}, **FLAGS}


@pytest.mark.parametrize("lane", ["A", "HK"])
def test_registry_lane_config_is_independent_and_checks_receipt(tmp_path, monkeypatch, lane):
    env = bindings(tmp_path, monkeypatch, lane)
    seen = []
    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(compact_fixture(env["RECEIPT_ROOT"], lane)), "")
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path, runner=runner)
    result = registry(workload(lane), request(lane))
    assert result["status"] == "SUCCEEDED"
    assert result["receipt_verified"] is True
    assert ("--hk-tdx-root" not in seen[0][0]) if lane == "A" else ("--a-tdx-root" not in seen[0][0])


@pytest.mark.parametrize("defect", ["missing", "sha", "date", "lane", "status", "safety", "symlink", "envelope_safety"])
def test_registry_refuses_stdout_ready_without_exact_bound_receipt(tmp_path, monkeypatch, defect):
    env = bindings(tmp_path, monkeypatch, "A")
    # Populate unused HK settings too: the RED proves false-ready, not missing config.
    for key in HK_KEYS:
        monkeypatch.setenv("V35_RESEARCH_PANEL_" + key, str(tmp_path / key))
    mutation = {"date": {"target_date": "20260910"}, "lane": {"lane": "HK"},
                "status": {"status": "FAILED"}, "safety": {"orders_sent": True}}.get(defect)
    payload = compact_fixture(env["RECEIPT_ROOT"], "A", mutate=mutation)
    path = Path(env["RECEIPT_ROOT"]) / f"a-{DATE}.json"
    if defect == "missing":
        path.unlink()
    elif defect == "sha":
        path.write_bytes(path.read_bytes() + b" ")
    elif defect == "symlink":
        saved = tmp_path / "elsewhere.json"
        saved.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(saved)
    elif defect == "envelope_safety":
        payload["production_allowed"] = True
    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path, runner=runner)
    with pytest.raises(WorkloadExecutionError) as caught:
        registry(workload("A"), request("A"))
    assert caught.value.result["status"] == "FAILED"
    assert caught.value.result["receipt_verified"] is False


def test_registry_passes_host_and_cooperative_budget_explicitly(tmp_path, monkeypatch):
    env = bindings(tmp_path, monkeypatch, "A")
    monkeypatch.setenv("V35_A_SYNC_HOST", "fixture.invalid:7710")
    monkeypatch.setenv("V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS", "37.5")
    seen = []
    def runner(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(compact_fixture(env["RECEIPT_ROOT"], "A")), "")
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path, runner=runner)
    registry(workload("A"), request("A"))
    assert seen[0][seen[0].index("--a-host") + 1] == "fixture.invalid:7710"
    assert seen[0][seen[0].index("--a-sync-run-budget-seconds") + 1] == "37.5"


def cli_paths(tmp_path, lane="A"):
    keys = A_KEYS if lane == "A" else HK_KEYS
    result = {"--receipt-root": tmp_path / "receipts"}
    for key in keys:
        if key == "HK_PYTHON_EXECUTABLE":
            result["--hk-python-executable"] = Path(sys.executable)
        else:
            result["--" + key.lower().replace("_", "-")] = tmp_path / key.lower()
    return result


def argv_for(paths, lane="A"):
    return ["--date", DATE, "--lane", lane] + [part for option, path in paths.items() for part in (option, str(path))]


def test_public_entry_emits_single_small_envelope_and_preserves_full_receipt(tmp_path, monkeypatch, capsys):
    paths = cli_paths(tmp_path)
    # All bindings supplied in RED so original fails on stdout contract, not CLI.
    paths.update({key: value for key, value in cli_paths(tmp_path, "HK").items() if key not in paths})
    marker = paths["--a-tdx-root"] / "vipdoc/sz/lday/sz000001.day"
    marker.parent.mkdir(parents=True); marker.write_bytes(b"contract-fixture-not-marketdata")
    def sync(*_args, **_kwargs):
        print("authority diagnostics " * 300)
        return {"status": "READY", **FLAGS}
    full_rows = [{"evidence": "x" * 200, "ordinal": n} for n in range(600)]
    monkeypatch.setattr(panel, "run_windows_a_sync_authority", sync)
    monkeypatch.setattr(panel, "run_windows_a_formula_authority", lambda *_a, **_kw: {"status": "READY", "rows": full_rows, **FLAGS})
    monkeypatch.setattr(sys, "argv", ["panel", *argv_for(paths)])
    assert panel.main() == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert len(output.out.encode()) < 2048
    assert payload["status"] == "READY" and payload["lane"] == "A"
    assert "authority diagnostics" in output.err
    raw = (paths["--receipt-root"] / f"a-{DATE}.json").read_bytes()
    assert payload["lanes"]["A"]["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(json.loads(raw)["formula"]["rows"]) == 600


@pytest.mark.parametrize("lane", ["A", "HK"])
def test_public_no_date_fast_path_preserves_lane_receipt_for_registry(
    tmp_path, monkeypatch, capsys, lane
):
    """An idempotent public call must remain consumable by the fixed registry."""

    env = bindings(tmp_path, monkeypatch, lane)
    paths = cli_paths(tmp_path, lane)
    receipt_root = Path(env["RECEIPT_ROOT"])
    paths["--receipt-root"] = receipt_root
    if lane == "A":
        panel._receipt(receipt_root, "A", DATE, {"status": "READY", "backtest_pointer_ready": True, **FLAGS})
        monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_args: True)
    else:
        panel._receipt(
            receipt_root,
            "HK",
            DATE,
            {"status": "READY", "row_count": 600, "coverage_rate": 1.0, "sha256": "fixture", **FLAGS},
        )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 11, 17, 30, tzinfo=SHANGHAI)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(panel._datetime, "datetime", FrozenDateTime)

    def forbidden_runner(*_args, **_kwargs):
        raise AssertionError("exact ready receipt must not invoke a runner")

    monkeypatch.setattr(panel, "run_windows_a_sync_authority", forbidden_runner)
    monkeypatch.setattr(panel, "run_windows_a_formula_authority", forbidden_runner)
    argv = ["panel", "--lane", lane]
    argv.extend(part for option, path in paths.items() for part in (option, str(path)))
    outputs = []
    for _ in range(2):
        monkeypatch.setattr(sys, "argv", argv)
        assert panel.main() == 0
        outputs.append(json.loads(capsys.readouterr().out))
        assert outputs[-1]["status"] == "ALREADY_READY"
        detail = outputs[-1]["lanes"][lane]
        assert detail["status"] == "READY"
        raw = (receipt_root / f"{lane.lower()}-{DATE}.json").read_bytes()
        assert detail["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
        assert detail["receipt_bytes"] == len(raw)
        assert outputs[-1]["runner_called"] is False

    dispatched = []

    def registry_runner(command, **_kwargs):
        dispatched.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(outputs[-1]), "")

    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path, runner=registry_runner)
    for _ in range(2):
        result = registry(workload(lane), request(lane))
        assert result["status"] == "SUCCEEDED"
        assert result["receipt_verified"] is True
    assert len(dispatched) == 2


def test_hk_public_entry_needs_no_a_binding_or_a_budget(tmp_path, monkeypatch, capsys):
    paths = cli_paths(tmp_path, "HK")
    monkeypatch.setenv("V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS", "not-an-A-config")
    monkeypatch.setattr(panel, "collect_hk_futu_rows", lambda *_a, **_k: {"status": "READY", "rows": [], "source_sha256": "fixture"})
    monkeypatch.setattr(panel, "pack_hk_day", lambda *_a, **_k: {"status": "READY"})
    monkeypatch.setattr(panel, "run_hk_0_2_authority", lambda *_a, **_k: {"status": "READY"})
    monkeypatch.setattr(sys, "argv", ["panel", *argv_for(paths, "HK")])
    assert panel.main() == 0
    assert json.loads(capsys.readouterr().out)["lanes"]["HK"]["status"] == "READY"
    assert not (paths["--receipt-root"] / f"a-{DATE}.json").exists()


def test_hk_ensure_exact_receipt_does_not_read_a_selector(tmp_path, monkeypatch):
    panel._receipt(tmp_path, "HK", DATE, {"status": "READY", "row_count": 600, "coverage_rate": 1.0, "sha256": "fixture", **FLAGS})
    def forbidden(*_a):
        raise AssertionError("HK must not read A selector")
    monkeypatch.setattr(panel, "selector_pointer_is_ready", forbidden)
    result = panel.ensure_after_1700(target_date=DATE, receipt_root=tmp_path,
        selector_pointer=tmp_path / "missing-a-pointer", lane="HK",
        now=datetime(2026, 9, 11, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        a_runner=forbidden, hk_runner=forbidden)
    assert result["status"] == "ALREADY_READY"
    assert panel.ensure_exit_code(result) == 0


def test_hk_ensure_does_not_inherit_a_retry_backoff(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "selector_pointer_is_ready", lambda *_: False)
    now = datetime(2026, 9, 11, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    common = dict(target_date=DATE, receipt_root=tmp_path, selector_pointer=tmp_path / "a", now=now)
    def failed(_):
        return {"status": "FAILED"}
    panel.ensure_after_1700(**common, lane="A", a_runner=failed, hk_runner=failed)
    calls = []
    def hk(date):
        calls.append(date)
        return {"status": "READY", "row_count": 600, "coverage_rate": 1, "sha256": "fixture", **FLAGS}
    result = panel.ensure_after_1700(**common, lane="HK", a_runner=failed, hk_runner=hk)
    assert result["status"] == "ATTEMPTED"
    assert calls == [DATE]


def test_panel_registry_respects_launcher_rejected_hk_runtime_before_collecting(tmp_path, monkeypatch):
    bindings(tmp_path, monkeypatch, "HK")
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path, runner=runner,
                                    hk_0_2_python_executable=tmp_path / "python.invalid")
    with pytest.raises(WorkloadExecutionError) as caught:
        registry(workload("HK"), request("HK"))
    assert calls == []
    assert caught.value.result["reason"] == "HK_RUNTIME_NOT_VERIFIED"


def test_real_dynamic_sync_import_registers_dataclass_module(tmp_path):
    loaded = panel._load_authority_module(Path(panel.__file__).with_name("a_share_daily_sync.py"), "candidate_sync_import")
    assert sys.modules["candidate_sync_import"] is loaded
    assert loaded.DailyTarget.__module__ == "candidate_sync_import"


def test_failed_dynamic_import_restores_previous_module(tmp_path):
    import types
    previous = types.ModuleType("candidate_import_rollback")
    sys.modules[previous.__name__] = previous
    fixture = tmp_path / "raising.py"
    fixture.write_text("raise RuntimeError('fixture-import-failure')\n")
    with pytest.raises(RuntimeError, match="fixture-import-failure"):
        panel._load_authority_module(fixture, previous.__name__)
    assert sys.modules[previous.__name__] is previous
