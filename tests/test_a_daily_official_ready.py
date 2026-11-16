"""Restore the four-file R2 overlay, then exercise the existing A source entry points."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs/handoffs/a_daily_official_ready_20261116"
R2 = Path.home() / ("Library/Application Support/com.lexi.v4.local/candidates/"
                    "v4-single-panel-daily-20261116-r2/main/app")
SHANGHAI = ZoneInfo("Asia/Shanghai")
DATE = "20261029"


def time_at(hour, minute, second=0):
    return datetime(2026, 10, 29, hour, minute, second, tzinfo=SHANGHAI)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def overlay(tmp_path_factory):
    inventory = json.loads((HANDOFF / "OVERLAY_INVENTORY.json").read_bytes())
    manifest = R2.parent / "release-manifest.json"
    if any(not path.exists() and not path.is_symlink() for path in (R2, manifest)):
        pytest.skip("The sealed Mac R2 Main runtime and role manifest are required for this native overlay test")
    assert sha(manifest) == inventory["baseline_manifest_sha256"]
    runtime = json.loads(manifest.read_bytes())
    assert runtime["release_id"] == inventory["release"] and Path(runtime["app_root"]) == R2
    files = {record["path"]: record["sha256"] for record in runtime["app_files"]}
    result = tmp_path_factory.mktemp("r2-overlay")
    for name, expected in inventory["files"].items():
        original = (R2 / name).read_bytes()
        assert hashlib.sha256(original).hexdigest() == expected["before_sha256"] == files[name]
        local = result / name
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(original)
    policy = inventory["unchanged_source_policy"]
    assert sha(R2 / policy["path"]) == policy["sha256"] == files[policy["path"]]
    (result / policy["path"]).write_bytes((R2 / policy["path"]).read_bytes())
    patch = HANDOFF / "CANDIDATE_OVERLAY.patch"
    assert sha(patch) == inventory["patch_sha256"]
    subprocess.run(["git", "apply", str(patch)], cwd=result, check=True, capture_output=True)
    for name, expected in inventory["files"].items():
        assert sha(result / name) == expected["after_sha256"]
    return result


@pytest.fixture
def load_module(overlay, monkeypatch):
    monkeypatch.syspath_prepend(str(R2))
    def load(name, source=overlay):
        path = source / Path(*name.split(".")).with_suffix(".py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module
    return load


def test_only_a_schedule_changes_and_historical_policy_stays_exact(overlay, monkeypatch):
    monkeypatch.syspath_prepend(str(R2))
    from infrastructure.scheduling.catalog import load_workload_catalog

    contract = "contracts/runtime_workloads.json"
    before = json.loads((R2 / contract).read_bytes())
    a_daily = next(item for item in before["workloads"] if item["workload_id"] == "research_panel_daily_a")
    assert a_daily["slots"] == ["1540", "1610", "1640"]
    a_daily["slots"] = ["1610", "1640"]
    assert json.loads((overlay / contract).read_bytes()) == before
    catalog = load_workload_catalog(overlay / contract)
    assert next(item for item in catalog.workloads if item.workload_id == "research_panel_daily_a").slots == ("1610", "1640")
    policy = "contracts/a_share_daily_source_policy.json"
    assert sha(overlay / policy) == sha(R2 / policy) == "008c3cc8ce9fa4569e78138dc585f148bc66dd01f6554320d7e8504d6164c19d"
    assert json.loads((overlay / policy).read_bytes())["earliest_slot"] == "1540"
    inventory = json.loads((HANDOFF / "OVERLAY_INVENTORY.json").read_bytes())
    assert set(inventory["files"]) == {contract, "ops/research_panel_daily_source.py",
                                     "ops/macos_research_panel_daily_gate.py",
                                     "infrastructure/scheduling/executor_registry.py"}


def test_source_waits_before_first_get_but_never_for_a_verified_cache(load_module, tmp_path):
    source = load_module("ops.research_panel_daily_source")
    packet = load_module("tests.test_a_share_daily_zip_source", source=R2).packet
    events = []
    def fetch():
        events.append("GET")
        return packet()

    with pytest.raises(source.QfqGateError, match="OFFICIAL_DAILY_SOURCE_WAIT_WINDOW"):
        source.acquire_daily_input(int(DATE), tmp_path, fetch=fetch, now=time_at(16, 9, 59), sleep=events.append)
    assert events == [] and not list(tmp_path.iterdir())

    moment = time_at(16, 10, 6).astimezone(timezone.utc)
    first = source.acquire_daily_input(int(DATE), tmp_path, fetch=fetch, now=moment, sleep=events.append)
    assert events == [9, "GET"]
    assert source.acquire_daily_input(int(DATE), tmp_path, fetch=fetch, now=time_at(16, 10), sleep=events.append) == first
    assert source.acquire_daily_input(int(DATE), tmp_path, fetch=fetch, now=time_at(16, 10).replace(day=30),
                                      sleep=events.append) == first
    assert events == [9, "GET"]


def test_source_retry_at_161015_preserves_two_attempts_and_wait_receipt(load_module, tmp_path):
    source = load_module("ops.research_panel_daily_source")
    events = []
    def absent():
        events.append("GET")
        raise urllib.error.HTTPError("official", 404, "not ready", {}, None)

    with pytest.raises(source.QfqGateError, match="OFFICIAL_DAILY_SOURCE_NOT_READY"):
        source.acquire_daily_input(int(DATE), tmp_path, fetch=absent, now=time_at(16, 10, 15), sleep=events.append)
    assert events == ["GET", 2, "GET"]
    assert json.loads(next(tmp_path.rglob("WAIT.json")).read_bytes())["status"] == "SOURCE_NOT_READY"
    assert not list(tmp_path.rglob("input.json"))


@pytest.mark.parametrize(("slot", "state", "hour", "minute", "expected"), [
    ("1610", "missing", 16, 10, True),
    ("1610", "failed", 16, 10, True),
    ("1610", "corrupt", 16, 10, False),
    ("1610", "symlink", 16, 10, False),
    ("1610", "directory", 16, 10, False),
    ("1610", "root_alias", 16, 10, False),
    ("1610", "wrong_date", 16, 10, False),
    ("1610", "missing", 16, 9, False),
    ("1540", "missing", 16, 30, False),
    ("1640", "missing", 16, 40, False),
    ("1640", "failed", 16, 40, True),
])
def test_actual_executor_a_start_or_retry(load_module, monkeypatch, tmp_path, slot, state, hour, minute, expected):
    registry = load_module("infrastructure.scheduling.executor_registry")
    root = tmp_path.resolve()
    receipt = root / f"a-{DATE}.json"
    if state in {"failed", "wrong_date"}:
        value = dict(schema_version="v3.macos.research_panel_receipt.v1", lane="A", status="FAILED",
                     target_date=DATE if state == "failed" else "20261028", production_allowed=False,
                     buy_gate_updated=False, orders_sent=False)
        receipt.write_text(json.dumps(value))
    if state == "corrupt":
        receipt.write_text("{")
    if state == "symlink":
        receipt.symlink_to(root / "not-a-dated-receipt")
    if state == "directory":
        receipt.mkdir()
    if state == "root_alias":
        real = root / "real"
        real.mkdir()
        root = root / "alias"
        root.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("V4_RESEARCH_PANEL_RECEIPT_ROOT", str(root))
    monkeypatch.setenv("V4_RESEARCH_PANEL_A_SELECTOR_POINTER", str(root / "selector.txt"))
    monkeypatch.setenv("V4_RESEARCH_PANEL_A_BACKTEST_POINTER", str(root / "backtest.txt"))
    monkeypatch.setattr(registry, "shanghai_now", lambda: time_at(hour, minute))
    executor = registry.FixedExecutorRegistry(data_root=root)
    calls = []
    monkeypatch.setattr(executor, "_research_panel_daily", lambda request, lane: calls.append(lane) or {"status": "SUCCEEDED"})
    request = registry.DispatchRequest(DATE, DATE, DATE, slot, "LIVE")
    if expected:
        assert executor._run_a_daily_source(request)["status"] == "SUCCEEDED"
        assert calls == ["A"]
    else:
        with pytest.raises(registry.WorkloadExecutionError):
            executor._run_a_daily_source(request)
        assert calls == []


def test_wrapper_before_1610_and_legacy_exit_compatibility(load_module, monkeypatch, tmp_path):
    gate = load_module("ops.macos_research_panel_daily_gate")
    monkeypatch.setattr(gate, "selector_pointer_is_ready", lambda *_: True)
    monkeypatch.setattr(gate, "_a_lane_receipt_ready", lambda *_: (True, True))
    monkeypatch.setattr(gate, "_hk_lane_receipt_ready", lambda *_: False)
    def unexpected(_):
        pytest.fail("test must not invoke a lane runner")
    kwargs = dict(target_date=DATE, receipt_root=tmp_path, selector_pointer=tmp_path / "selector.txt",
                  a_runner=unexpected, hk_runner=unexpected)
    outcome = gate.ensure_after_1700(**kwargs, lane="A", now=time_at(16, 9, 59))
    assert outcome["status"] == "BEFORE_1610" and outcome["runner_called"] is False
    assert gate.ensure_exit_code(outcome) == 0
    assert gate.ensure_after_1700(**kwargs, lane="A", now=time_at(16, 10))["status"] == "ALREADY_READY"
    assert gate.ensure_after_1700(**kwargs, lane="HK", now=time_at(16, 10))["status"] == "BEFORE_1700"
    for status in ("BEFORE_1540", "BEFORE_1610", "BEFORE_1700"):
        assert gate.ensure_exit_code({"status": status}) == 0
        assert gate.ensure_exit_code({"status": status, "lane_ready": False}) == 0
