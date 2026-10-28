from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)


_BINDING_ENV = (
    "V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_PATH",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_ID",
    "V35_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256",
)
_HK_INPUTS = {
    "V35_RESEARCH_PANEL_RECEIPT_ROOT": "receipt-root",
    "V35_RESEARCH_PANEL_HK_TDX_ROOT": "hk-tdx-root",
    "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT": "updater-script",
    "V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE": "hk-python",
    "V35_RESEARCH_PANEL_HK_ASSET_ROOT": "asset-root",
}
_A_INPUTS = {
    "V35_RESEARCH_PANEL_A_RECEIPT_ROOT": "a-receipt-root",
    "V35_RESEARCH_PANEL_A_TDX_ROOT": "a-tdx-root",
    "V35_RESEARCH_PANEL_A_SYNC_SCRIPT": "a-sync-script",
    "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT": "a-formula-script",
    "V35_RESEARCH_PANEL_A_SEED_PANEL": "a-seed-panel",
    "V35_RESEARCH_PANEL_A_DATA_ROOT": "a-data-root",
    "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": "a-selector-pointer",
    "V35_RESEARCH_PANEL_A_BACKTEST_POINTER": "a-backtest-pointer",
    "V35_RESEARCH_PANEL_A_SELECTOR_SEED": "a-selector-seed",
    "V35_RESEARCH_PANEL_A_BACKTEST_SEED": "a-backtest-seed",
    "V35_RESEARCH_PANEL_A_CONTRACT_CSV": "a-contract-csv",
    "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA": "a-canonical-formula",
    "V35_RESEARCH_PANEL_A_RETURN_ROOT": "a-return-root",
}
_REQUEST = DispatchRequest(
    "20261001", "20261001", "20261001", "1720", DispatchMode.LIVE
)


def _receipt_payload(lane: str, target_date: str) -> dict[str, object]:
    return {
        "schema_version": "v3.macos.research_panel_receipt.v1",
        "target_date": target_date,
        "lane": lane,
        "status": "READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _envelope(lane: str, receipt_path: Path) -> str:
    raw = receipt_path.read_bytes()
    return json.dumps(
        {
            "schema_version": "v3.macos.research_panel_authority_envelope.v1",
            "target_date": _REQUEST.business_date,
            "requested_lane": lane,
            "lanes": {
                lane: {
                    "status": "READY",
                    "receipt_bytes": len(raw),
                    "receipt_sha256": hashlib.sha256(raw).hexdigest(),
                }
            },
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )


def _configure(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name in _BINDING_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in (*_HK_INPUTS, *_A_INPUTS):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _runner_with_receipt(calls: list[tuple[list[str], dict[str, object]]]):
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        lane = command[command.index("--lane") + 1]
        receipt_root = Path(command[command.index("--receipt-root") + 1])
        receipt_path = receipt_root / f"{lane.lower()}-{_REQUEST.business_date}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(_receipt_payload(lane, _REQUEST.business_date)))
        return subprocess.CompletedProcess(
            command, 0, _envelope(lane, receipt_path), ""
        )

    return runner


def test_unconfigured_hk_and_a_keep_the_original_child_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hk_receipts = tmp_path / "legacy-hk-receipts"
    a_receipts = tmp_path / "legacy-a-receipts"
    _configure(
        monkeypatch,
        {
            **_HK_INPUTS,
            **_A_INPUTS,
            "V35_RESEARCH_PANEL_RECEIPT_ROOT": str(hk_receipts),
            "V35_RESEARCH_PANEL_A_RECEIPT_ROOT": str(a_receipts),
        },
    )
    calls: list[tuple[list[str], dict[str, object]]] = []
    registry = FixedExecutorRegistry(
        tmp_path / "data", repo_root=tmp_path, runner=_runner_with_receipt(calls)
    )

    hk_result = registry._research_panel_daily(_REQUEST, lane="HK")
    a_result = registry._research_panel_daily(_REQUEST, lane="A")

    assert hk_result["status"] == a_result["status"] == "SUCCEEDED"
    assert [call[0][1:3] for call in calls] == [
        ["-m", "ops.macos_research_panel_daily"],
        ["-m", "ops.macos_research_panel_daily"],
    ]
    assert [call[1] for call in calls] == [
        {"cwd": tmp_path, "timeout_seconds": 300, "env": None},
        {"cwd": tmp_path, "timeout_seconds": 300, "env": None},
    ]


def test_bad_hk_binding_fails_before_child_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_root = tmp_path / "candidate" / "app"
    app_root.mkdir(parents=True)
    manifest_path = app_root.parent / "release-manifest.json"
    manifest_path.write_text("{}")
    _configure(
        monkeypatch,
        {
            **_HK_INPUTS,
            **dict(zip(_BINDING_ENV, (str(app_root), str(manifest_path), "0" * 64, "candidate", "0" * 64))),
        },
    )
    calls: list[tuple[list[str], dict[str, object]]] = []
    registry = FixedExecutorRegistry(
        tmp_path / "data", repo_root=tmp_path, runner=_runner_with_receipt(calls)
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry._research_panel_daily(_REQUEST, lane="HK")

    assert raised.value.result["failure_class"] == "INVALID_INPUT"
    assert raised.value.result["reason"] == "HK_CHILD_BINDING_MANIFEST_SHA_MISMATCH"
    assert calls == []


def test_hk_child_imports_the_pinned_candidate_without_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_root_raw = os.environ.get("R3A_HK_TEST_APP_ROOT", "")
    manifest_path_raw = os.environ.get("R3A_HK_TEST_MANIFEST_PATH", "")
    manifest_sha = os.environ.get("R3A_HK_TEST_MANIFEST_SHA256", "")
    release_id = os.environ.get("R3A_HK_TEST_RELEASE_ID", "")
    module_sha = os.environ.get("R3A_HK_TEST_MODULE_SHA256", "")
    if not all((app_root_raw, manifest_path_raw, manifest_sha, release_id, module_sha)):
        pytest.skip("R3A candidate identity pins were not supplied for the offline child canary")

    app_root = Path(app_root_raw)
    receipt_root = tmp_path / "bound-hk-receipts"
    _configure(
        monkeypatch,
        {
            **_HK_INPUTS,
            "V35_RESEARCH_PANEL_RECEIPT_ROOT": str(receipt_root),
            **dict(zip(_BINDING_ENV, (app_root_raw, manifest_path_raw, manifest_sha, release_id, module_sha))),
            "V35_APP_ROOT": "/stale/old-release/app",
            "V35_RELEASE_ID": "stale-old-release",
            "V35_RELEASE_MANIFEST_PATH": "/stale/old-release/manifest.json",
            "V35_RELEASE_MANIFEST_SHA256": "f" * 64,
            "V4_MANAGER_RESEARCH_STATE_ROOT": "/stale/manager/state",
            "PYTHONPATH": "/stale/old-release/app:/stale/shared-package",
        },
    )

    child_report: dict[str, object] = {}

    def canary_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["-m", "ops.macos_research_panel_daily"]
        assert kwargs["cwd"] == app_root
        child_env = kwargs["env"]
        assert isinstance(child_env, dict)
        assert child_env["V35_APP_ROOT"] == str(app_root)
        assert child_env["V35_RELEASE_ID"] == release_id
        assert child_env["V35_RELEASE_MANIFEST_PATH"] == manifest_path_raw
        assert child_env["V35_RELEASE_MANIFEST_SHA256"] == manifest_sha
        assert child_env["PRODUCTION_ALLOWED"] == "false"
        assert child_env["BUY_GATE_UPDATED"] == "false"
        assert child_env["ORDERS_SENT"] == "false"
        assert "/stale/old-release/app" not in child_env["PYTHONPATH"]
        assert "/stale/shared-package" not in child_env["PYTHONPATH"]
        assert "V4_MANAGER_RESEARCH_STATE_ROOT" not in child_env

        script = r"""
import json
import socket
import sys
from pathlib import Path
socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network blocked"))
socket.create_connection = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network blocked"))
import ops.macos_research_panel_daily as panel
print(json.dumps({"module_file": str(Path(panel.__file__).resolve()), "python": sys.executable}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=kwargs["cwd"],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        child_report.update(json.loads(completed.stdout))
        assert child_report["module_file"] == str(app_root / "ops/macos_research_panel_daily.py")
        assert Path(str(child_report["python"])).resolve() == Path(sys.executable).resolve()

        receipt_path = receipt_root / f"hk-{_REQUEST.business_date}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(_receipt_payload("HK", _REQUEST.business_date)))
        return subprocess.CompletedProcess(command, 0, _envelope("HK", receipt_path), "")

    registry = FixedExecutorRegistry(
        tmp_path / "data", repo_root=tmp_path, runner=canary_runner
    )
    result = registry._research_panel_daily(_REQUEST, lane="HK")

    assert result["status"] == "SUCCEEDED"
    assert result["receipt_verified"] is True
    assert child_report["module_file"] == str(app_root / "ops/macos_research_panel_daily.py")


def test_inactive_r9_candidate_routes_only_hk_child_to_bound_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler_app_raw = os.environ.get("R9_HK_TEST_SCHEDULER_APP_ROOT", "")
    api_app_raw = os.environ.get("R3A_HK_TEST_APP_ROOT", "")
    manifest_path = os.environ.get("R3A_HK_TEST_MANIFEST_PATH", "")
    manifest_sha = os.environ.get("R3A_HK_TEST_MANIFEST_SHA256", "")
    release_id = os.environ.get("R3A_HK_TEST_RELEASE_ID", "")
    module_sha = os.environ.get("R3A_HK_TEST_MODULE_SHA256", "")
    if not all((scheduler_app_raw, api_app_raw, manifest_path, manifest_sha, release_id, module_sha)):
        pytest.skip("inactive scheduler and R3A candidate identity pins were not supplied")

    scheduler_app = Path(scheduler_app_raw)
    receipt_root = tmp_path / "r9-candidate-receipts"
    hk_tdx_root = tmp_path / "hk-tdx-fixture"
    day_file = hk_tdx_root / "vipdoc/ds/lday/71#00001.day"
    day_file.parent.mkdir(parents=True)
    day_file.write_bytes(b"synthetic offline HK day-file bytes")
    outer_env = dict(os.environ)
    outer_env["PYTHONPATH"] = str(scheduler_app)
    outer_env["PYTHONNOUSERSITE"] = "1"
    outer_env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in tuple(outer_env):
        if key.startswith("V4_MANAGER_") or key.startswith("V35_RELEASE_"):
            outer_env.pop(key, None)
    for key in (
        "V35_APP_ROOT",
        "V35_UPSTREAM_FINGERPRINT",
        "PYTHONHOME",
        "PYTHONUSERBASE",
    ):
        outer_env.pop(key, None)
    outer_env.update(
        {
            "V35_RESEARCH_PANEL_RECEIPT_ROOT": str(receipt_root),
            "R35_TEST_DATA_ROOT": str(tmp_path / "registry-data"),
            "V35_RESEARCH_PANEL_A_TDX_ROOT": "a-tdx",
            "V35_RESEARCH_PANEL_HK_TDX_ROOT": str(hk_tdx_root),
            "V35_RESEARCH_PANEL_A_SYNC_SCRIPT": "a-sync",
            "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT": "a-formula",
            "V35_RESEARCH_PANEL_A_SEED_PANEL": "a-seed",
            "V35_RESEARCH_PANEL_A_DATA_ROOT": "a-data",
            "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": "a-selector-pointer",
            "V35_RESEARCH_PANEL_A_BACKTEST_POINTER": "a-backtest-pointer",
            "V35_RESEARCH_PANEL_A_SELECTOR_SEED": "a-selector-seed",
            "V35_RESEARCH_PANEL_A_BACKTEST_SEED": "a-backtest-seed",
            "V35_RESEARCH_PANEL_A_CONTRACT_CSV": "a-contract",
            "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA": "a-canonical",
            "V35_RESEARCH_PANEL_A_RETURN_ROOT": "a-return",
            "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT": "hk-updater",
            "V35_RESEARCH_PANEL_HK_ASSET_ROOT": "hk-assets",
            _BINDING_ENV[0]: api_app_raw,
            _BINDING_ENV[1]: manifest_path,
            _BINDING_ENV[2]: manifest_sha,
            _BINDING_ENV[3]: release_id,
            _BINDING_ENV[4]: module_sha,
        }
    )
    script = r"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError

app_root = Path(os.environ["R35_TEST_SCHEDULER_APP_ROOT"])
expected_api_root = Path(os.environ["V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT"])
request = DispatchRequest("20261001", "20261001", "20261001", "1720", DispatchMode.LIVE)
reports = []
route_reports = []

def runner(command, *, cwd, timeout_seconds, env):
    assert command[1:3] == ["-m", "ops.macos_research_panel_daily"]
    args = command[3:]
    def value_after(flag):
        return args[args.index(flag) + 1]
    lane = value_after("--lane")
    if lane == "HK" and not os.environ.get("V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT"):
        assert cwd == app_root
        assert env is None
        route_reports.append({"lane": lane, "cwd": str(cwd), "env_is_none": True})
        return subprocess.CompletedProcess(command, 1, "", "offline unconfigured HK route boundary check")
    if lane == "A":
        assert cwd == app_root
        assert env is None
        route_reports.append({"lane": lane, "cwd": str(cwd), "env_is_none": True})
        return subprocess.CompletedProcess(command, 1, "", "offline A route boundary check")
    assert cwd == expected_api_root
    assert env["V35_APP_ROOT"] == str(expected_api_root)
    assert env["V35_RELEASE_ID"] == os.environ["V35_RESEARCH_PANEL_HK_CHILD_RELEASE_ID"]
    assert env["PRODUCTION_ALLOWED"] == "false"
    assert env["BUY_GATE_UPDATED"] == "false"
    assert env["ORDERS_SENT"] == "false"
    assert "V4_MANAGER_RESEARCH_STATE_ROOT" not in env
    probe = r'''import json, socket, sys
from pathlib import Path
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network blocked"))
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network blocked"))
import ops.macos_research_panel_daily as panel
print(json.dumps({"module_file": str(Path(panel.__file__).resolve()), "python": sys.executable}))'''
    completed = subprocess.run([sys.executable, "-c", probe], cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["module_file"] == str(expected_api_root / "ops/macos_research_panel_daily.py")
    reports.append(report)
    target_date = value_after("--date")
    receipt_root = Path(value_after("--receipt-root"))
    receipt_path = receipt_root / f"{lane.lower()}-{target_date}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(Path(os.environ["V35_RESEARCH_PANEL_HK_TDX_ROOT"],
                                 "vipdoc/ds/lday/71#00001.day").read_bytes()).hexdigest()
    receipt = {"schema_version": "v3.macos.research_panel_receipt.v1",
               "target_date": target_date, "lane": lane, "status": "READY",
               "sha256": hashlib.sha256(digest.encode()).hexdigest(),
               "row_count": 1, "coverage_rate": 1.0, "file_count": 1,
               "files": [{"status": "READY", "target_date": target_date,
                          "path": str(Path(os.environ["V35_RESEARCH_PANEL_HK_TDX_ROOT"],
                                            "vipdoc/ds/lday/71#00001.day")),
                          "sha256": digest, "row_count": 1, "coverage_rate": 1.0,
                          "production_allowed": False, "buy_gate_updated": False,
                          "orders_sent": False}],
               "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    receipt_path.write_text(json.dumps(receipt))
    raw = json.dumps({"schema_version": "v3.macos.research_panel_authority_envelope.v1",
                      "target_date": target_date, "requested_lane": lane,
                      "lanes": {lane: {"status": "READY"}},
                      "production_allowed": False, "buy_gate_updated": False,
                      "orders_sent": False})
    return subprocess.CompletedProcess(command, 0, raw, "")

registry = FixedExecutorRegistry(Path(os.environ["R35_TEST_DATA_ROOT"]), repo_root=app_root,
                                 runner=runner)
try:
    result = registry._research_panel_daily(request, lane="HK")
except Exception as error:
    print(json.dumps({"error": str(error), "result": getattr(error, "result", {}),
                      "reports": reports}))
    raise
try:
    registry._research_panel_daily(request, lane="A")
except Exception:
    pass
else:
    raise AssertionError("offline A boundary fixture must remain non-ready")
saved_binding = {key: os.environ.pop(key) for key in (
    "V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_PATH",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_ID",
    "V35_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256",
)}
try:
    registry._research_panel_daily(request, lane="HK")
except WorkloadExecutionError:
    pass
else:
    raise AssertionError("offline unconfigured HK boundary fixture must remain non-ready")
os.environ.update(saved_binding)
invalid_called = []
original_manifest_sha = os.environ["V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256"]
os.environ["V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256"] = "0" * 64
invalid_registry = FixedExecutorRegistry(
    Path(os.environ["R35_TEST_DATA_ROOT"]), repo_root=app_root,
    runner=lambda *args, **kwargs: invalid_called.append(args) or subprocess.CompletedProcess(args[0], 0, "", ""),
)
try:
    invalid_registry._research_panel_daily(request, lane="HK")
except WorkloadExecutionError as error:
    invalid_pin_reason = error.result.get("reason")
else:
    raise AssertionError("invalid HK candidate manifest pin must fail closed")
os.environ["V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256"] = original_manifest_sha
assert invalid_pin_reason == "HK_CHILD_BINDING_MANIFEST_SHA_MISMATCH"
assert invalid_called == []
print(json.dumps({"status": result.get("status"), "lane_status": result.get("lane_status"),
                  "reports": reports, "route_reports": route_reports,
                  "invalid_pin_reason": invalid_pin_reason}))
"""
    outer_env["R35_TEST_SCHEDULER_APP_ROOT"] = str(scheduler_app)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=scheduler_app,
        env=outer_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "SUCCEEDED"
    assert result["lane_status"] == "READY"
    assert result["reports"][0]["module_file"] == str(
        Path(api_app_raw) / "ops/macos_research_panel_daily.py"
    )
    assert result["route_reports"] == [
        {"lane": "A", "cwd": str(scheduler_app), "env_is_none": True},
        {"lane": "HK", "cwd": str(scheduler_app), "env_is_none": True},
    ]
    assert result["invalid_pin_reason"] == "HK_CHILD_BINDING_MANIFEST_SHA_MISMATCH"
