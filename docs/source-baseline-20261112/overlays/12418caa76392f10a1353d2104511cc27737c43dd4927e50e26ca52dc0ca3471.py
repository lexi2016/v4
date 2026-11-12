from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
from ops import run_v4_macos_scheduler as scheduler


SHANGHAI = ZoneInfo("Asia/Shanghai")
REPO = Path(__file__).resolve().parents[1]


def test_scheduler_start_replaces_all_stale_proxy_environment_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    original = dict(os.environ)
    stale_keys = (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "Http_Proxy",
        "hTtPs_PrOxY",
        "No_Proxy",
    )
    try:
        for key in stale_keys:
            os.environ[key] = "http://127.0.0.1:7890"

        applied = scheduler.apply_research_proxy_environment()

        generic_proxy_keys = [
            key
            for key in os.environ
            if key.upper().endswith("_PROXY") and key.upper() not in {"NO_PROXY"}
        ]
        assert generic_proxy_keys == []
        assert "No_Proxy" not in os.environ
        assert os.environ["NO_PROXY"] == "127.0.0.1,localhost,::1"
        assert os.environ["no_proxy"] == "127.0.0.1,localhost,::1"
        assert applied["NO_PROXY"] == "127.0.0.1,localhost,::1"
    finally:
        for key in tuple(os.environ):
            os.environ.pop(key, None)
        for key, value in original.items():
            os.environ[key] = value


def test_shared_stage_child_environment_has_no_stale_proxy_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    original = dict(os.environ)
    captured: list[dict[str, str]] = []
    try:
        for key in ("ALL_PROXY", "all_proxy", "Http_Proxy", "hTtPs_PrOxY", "No_Proxy"):
            os.environ[key] = "http://127.0.0.1:7890"

        monkeypatch.setattr(
            scheduler,
            "resolve_selector_panel",
            lambda _selector_root, _business_date: tmp_path / "selector.parquet",
        )
        monkeypatch.setattr(
            scheduler,
            "ensure_stage_candidate_input",
            lambda **_kwargs: {
                "status": "READY",
                "row_count": 1,
                "run_id": "verified-1",
                "current_path": str(tmp_path / "verified-current.json"),
                "idempotent": False,
            },
        )

        def materializer(_data_root: Path, _business_date: str) -> dict[str, Any]:
            return {
                "status": "READY",
                "row_count": 1,
                "artifact": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
            }

        def runner(command, *, cwd, timeout, capture_output, text, encoding, errors, check, shell, env):
            del cwd, timeout, capture_output, text, encoding, errors, check, shell
            captured.append(dict(env))
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "status": "READY",
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                ),
                "",
            )

        result = scheduler.run_shared_stage_acquisition(
            business_date="20260828",
            slot="0935",
            data_root=tmp_path / "data",
            shared_data_root=tmp_path / "shared-data",
            shared_package_root=tmp_path / "shared-package",
            selector_data_root=tmp_path / "selector-root",
            timeout_seconds=1,
            process_runner=runner,
            universe_materializer=materializer,
        )

        assert result["status"] == "READY"
        assert len(captured) == 1
        child_proxy_keys = [
            key
            for key in captured[0]
            if key.upper().endswith("_PROXY") and key.upper() not in {"NO_PROXY"}
        ]
        assert child_proxy_keys == []
        assert "No_Proxy" not in captured[0]
        assert captured[0]["NO_PROXY"] == "127.0.0.1,localhost,::1"
        assert captured[0]["no_proxy"] == "127.0.0.1,localhost,::1"
    finally:
        for key in tuple(os.environ):
            os.environ.pop(key, None)
        for key, value in original.items():
            os.environ[key] = value


@pytest.mark.parametrize("universe_status", ["READY", "SUPERSEDED"])
def test_shared_stage_acquisition_accepts_successor_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    universe_status: str,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "resolve_selector_panel",
        lambda _selector_root, _business_date: tmp_path / "selector.parquet",
    )
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: {
            "status": universe_status,
            "row_count": 421,
            "run_id": "verified-421",
            "current_path": str(tmp_path / "verified-current.json"),
            "idempotent": False,
        },
    )

    def materializer(_data_root: Path, _business_date: str) -> dict:
        return {
            "status": universe_status,
            "row_count": 421,
            "artifact": {
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }

    def runner(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "ok": True,
                    "status": "READY",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            ),
            "",
        )

    result = scheduler.run_shared_stage_acquisition(
        business_date="20260902",
        slot="0935",
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared-data",
        shared_package_root=tmp_path / "shared-package",
        selector_data_root=tmp_path / "selector-root",
        timeout_seconds=1,
        process_runner=runner,
        universe_materializer=materializer,
    )

    assert result["status"] == "READY"
    assert result["stage_acquisition_universe"]["status"] == universe_status
    assert result["stage_acquisition_universe"]["row_count"] == 421


@pytest.mark.parametrize("universe_status", ["CANNOT_CONFIRM", "FAILED"])
def test_shared_stage_acquisition_rejects_non_success_status(
    tmp_path: Path,
    universe_status: str,
) -> None:
    def materializer(_data_root: Path, _business_date: str) -> dict:
        return {
            "status": universe_status,
            "row_count": 421,
            "artifact": {
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }

    with pytest.raises(RuntimeError, match="STAGE_ACQUISITION_UNIVERSE_NOT_READY"):
        scheduler.run_shared_stage_acquisition(
            business_date="20260902",
            slot="0935",
            data_root=tmp_path / "data",
            shared_data_root=tmp_path / "shared-data",
            shared_package_root=tmp_path / "shared-package",
            selector_data_root=tmp_path / "selector-root",
            timeout_seconds=1,
            process_runner=lambda *_args, **_kwargs: pytest.fail(
                "non-success stage input must not dispatch"
            ),
            universe_materializer=materializer,
        )


def test_catalog_registers_exact_recovery_workloads() -> None:
    catalog = load_workload_catalog()
    by_id = {item.workload_id: item for item in catalog.workloads}

    assert by_id["wechat_preselection_sync"].slots == ("0901", "2001")
    assert by_id["wechat_preselection_sync"].target_date_role == "TARGET_DATE"
    assert by_id["review_core_pool_pipeline"].slots == ("2115",)
    assert by_id["research_panel_runtime_evidence"].slots == ("1730",)
    assert by_id["research_panel_daily_a"].slots == ("1700",)
    assert by_id["research_panel_daily_a"].market_scope.value == "A_SHARE"
    assert by_id["research_panel_daily_hk"].slots == ("1720",)
    assert by_id["research_panel_daily_hk"].market_scope.value == "HK_CONNECT"
    assert all(item.safety.production_allowed is False for item in by_id.values())


def _us_market_digest_workload():
    return next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == "us_market_digest"
    )


@pytest.mark.parametrize(
    ("business_date", "slot", "us_session_date", "capture_phase"),
    (
        ("20260819", "2100", "20260819", "PRE_OPEN"),
        ("20260821", "0415", "20260820", "POST_CLOSE"),
        ("20260114", "2200", "20260114", "PRE_OPEN"),
        ("20260116", "0515", "20260115", "POST_CLOSE"),
    ),
)
def test_registry_dispatches_us_market_digest_for_each_dst_slot(
    tmp_path: Path,
    business_date: str,
    slot: str,
    us_session_date: str,
    capture_phase: str,
) -> None:
    calls = []

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append((command, cwd, timeout_seconds, env))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "status": "READY",
                    "payload_path": str(tmp_path / "us.json"),
                    "payload_sha256": "us-payload-sha",
                    "capture_origin": "ORIGINAL_TIME_CAPTURE",
                    "original_time_capture": True,
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=REPO,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=business_date,
        slot=slot,
        mode=DispatchMode.LIVE,
    )

    result = registry(_us_market_digest_workload(), request)

    assert result["status"] == "SUCCEEDED"
    assert result["capture_status"] == "READY"
    assert result["capture_phase"] == capture_phase
    assert result["us_session_date"] == us_session_date
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
    assert len(calls) == 1
    argv = calls[0][0]
    assert argv[1:3] == ["-m", "ops.us_market_digest"]
    assert argv[argv.index("--data-root") + 1] == str(tmp_path / "data")
    assert argv[argv.index("--trade-date") + 1] == us_session_date
    assert argv[argv.index("--capture-phase") + 1] == capture_phase
    assert argv[argv.index("--timeout") + 1] == "10"


@pytest.mark.parametrize("capture_status", ["READY", "READY_EMPTY"])
def test_registry_accepts_us_market_digest_ready_statuses(
    tmp_path: Path, capture_status: str
) -> None:
    calls = []

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"status": capture_status}),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=REPO,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260819",
        business_date="20260819",
        target_date="20260819",
        slot="2100",
        mode=DispatchMode.LIVE,
    )

    result = registry(_us_market_digest_workload(), request)

    assert result["status"] == "SUCCEEDED"
    assert result["capture_status"] == capture_status
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stdout", "failure_class"),
    (("not-json", "CONTRACT"), (json.dumps({"status": "NOT_READY"}), "UPSTREAM_NOT_READY")),
)
def test_registry_rejects_us_market_digest_malformed_or_not_ready_results(
    tmp_path: Path, stdout: str, failure_class: str
) -> None:
    calls = []

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=REPO,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260819",
        business_date="20260819",
        target_date="20260819",
        slot="2100",
        mode=DispatchMode.LIVE,
    )

    with pytest.raises(WorkloadExecutionError) as caught:
        registry(_us_market_digest_workload(), request)

    assert caught.value.result["failure_class"] == failure_class
    assert caught.value.result["status"] == "FAILED"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("business_date", "slot"),
    (("20260819", "2200"), ("20260114", "0415")),
)
def test_registry_inactive_us_market_digest_slot_is_not_due_without_child(
    tmp_path: Path, business_date: str, slot: str
) -> None:
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("inactive US seasonal slot must not start a child")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=REPO,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=business_date,
        slot=slot,
        mode=DispatchMode.LIVE,
    )

    result = registry(_us_market_digest_workload(), request)

    assert result["status"] == "SUCCEEDED"
    assert result["capture_status"] == "NOT_DUE"
    assert result["capture_slot"] == slot
    assert calls == []


def test_research_panel_slots_are_chronological() -> None:
    positions = [scheduler.ALL_SLOTS.index(slot) for slot in ("1700", "1710", "1720", "1730")]

    assert positions == sorted(positions)


@pytest.mark.parametrize(
    ("workload_id", "slot", "lane", "expected_status_key"),
    (
        ("research_panel_daily_a", "1700", "A", "A"),
        ("research_panel_daily_hk", "1720", "HK", "HK"),
    ),
)
def test_registry_dispatches_research_panel_daily_lanes_to_exact_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workload_id: str,
    slot: str,
    lane: str,
    expected_status_key: str,
) -> None:
    calls: list[list[str]] = []
    receipt_root = tmp_path / "receipts"

    for name in (
        "V4_RESEARCH_PANEL_RECEIPT_ROOT",
        "V4_RESEARCH_PANEL_A_TDX_ROOT",
        "V4_RESEARCH_PANEL_HK_TDX_ROOT",
        "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "V4_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "V4_RESEARCH_PANEL_A_SEED_PANEL",
        "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "V4_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "V4_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "V4_RESEARCH_PANEL_A_SELECTOR_SEED",
        "V4_RESEARCH_PANEL_A_BACKTEST_SEED",
        "V4_RESEARCH_PANEL_A_CONTRACT_CSV",
        "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "V4_RESEARCH_PANEL_A_RETURN_ROOT",
        "V4_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
        "V4_RESEARCH_PANEL_HK_ASSET_ROOT",
    ):
        monkeypatch.setenv(
            name,
            str(receipt_root if name == "V4_RESEARCH_PANEL_RECEIPT_ROOT" else tmp_path / name.lower()),
        )
    receipt_root.mkdir(parents=True)
    receipt_payload = {
        "schema_version": "v3.macos.research_panel_receipt.v1",
        "lane": lane,
        "target_date": "20260821",
        "status": "READY",
        "row_count": 1,
        "coverage_rate": 1.0,
        "sha256": "a" * 64,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if lane == "HK":
        artifact_root = Path(os.environ["V4_RESEARCH_PANEL_HK_TDX_ROOT"]) / "vipdoc" / "ds" / "lday"
        artifact_root.mkdir(parents=True)
        artifact_path = artifact_root / "71#00001.day"
        artifact_path.write_bytes(b"hk-panel-fixture")
        artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        receipt_payload.update(
            {
                "file_count": 1,
                "sha256": hashlib.sha256(artifact_sha.encode()).hexdigest(),
                "files": [
                    {
                        "status": "READY",
                        "target_date": "20260821",
                        "row_count": 1,
                        "coverage_rate": 1.0,
                        "sha256": artifact_sha,
                        "path": str(artifact_path),
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                ],
            }
        )
    (receipt_root / f"{lane.lower()}-20260821.json").write_text(
        json.dumps(receipt_payload), encoding="utf-8"
    )
    # The registered HK runtime is the only interpreter boundary.  A stale
    # raw research-panel executable must not be needed by the custom executor.
    monkeypatch.delenv("V4_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE", raising=False)

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        status = {"A": "NOT_REQUESTED", "HK": "NOT_REQUESTED"}
        status[lane] = "READY"
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_authority_envelope.v1",
                    "status": "READY",
                    "overall_status": "READY",
                    "target_date": "20260821",
                    "lane": lane,
                    "lanes": {key: {"status": value} for key, value in status.items()},
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        hk_0_2_python_executable=tmp_path / "hk02-python",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot=slot,
        mode=DispatchMode.LIVE,
    )
    workload = next(item for item in load_workload_catalog().workloads if item.workload_id == workload_id)

    result = registry(workload, request)

    assert result["status"] == "SUCCEEDED"
    assert result["lane"] == expected_status_key
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    argv = calls[0]
    assert argv[1:4] == ["-m", "ops.macos_research_panel_daily", "--date"]
    assert argv[argv.index("--lane") + 1] == lane
    assert argv[argv.index("--date") + 1] == "20260821"
    if lane == "HK":
        assert argv[argv.index("--hk-python-executable") + 1] == str(tmp_path / "hk02-python")


def test_research_panel_a_authority_rebuild_is_terminal_contract_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_root = tmp_path / "receipts"
    for name in (
        "V4_RESEARCH_PANEL_RECEIPT_ROOT",
        "V4_RESEARCH_PANEL_A_TDX_ROOT",
        "V4_RESEARCH_PANEL_HK_TDX_ROOT",
        "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "V4_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "V4_RESEARCH_PANEL_A_SEED_PANEL",
        "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "V4_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "V4_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "V4_RESEARCH_PANEL_A_SELECTOR_SEED",
        "V4_RESEARCH_PANEL_A_BACKTEST_SEED",
        "V4_RESEARCH_PANEL_A_CONTRACT_CSV",
        "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "V4_RESEARCH_PANEL_A_RETURN_ROOT",
        "V4_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
        "V4_RESEARCH_PANEL_HK_ASSET_ROOT",
    ):
        monkeypatch.setenv(
            name,
            str(receipt_root if name == "V4_RESEARCH_PANEL_RECEIPT_ROOT" else tmp_path / name.lower()),
        )

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_authority_envelope.v1",
                    "status": "PARTIAL",
                    "overall_status": "PARTIAL",
                    "target_date": "20260821",
                    "lane": "A",
                    "lanes": {
                        "A": {
                            "status": "PARTIAL",
                            "authority_status": "REBUILD_REQUIRED",
                            "reason": "A_SYNC_AUTHORITY_REBUILD_REQUIRED",
                        },
                        "HK": {"status": "NOT_REQUESTED"},
                    },
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        hk_0_2_python_executable=tmp_path / "hk02-python",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot="1700",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == "research_panel_daily_a"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["lane_status"] == "PARTIAL"
    assert result["reason"] == "A_SYNC_AUTHORITY_REBUILD_REQUIRED"
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["failure_class"] == "CONTRACT"


@pytest.mark.parametrize("receipt_state", ("missing", "zero_metrics", "content_tampered"))
def test_research_panel_hk_ready_envelope_requires_exact_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_state: str,
) -> None:
    receipt_root = tmp_path / "receipts"
    for name in (
        "V4_RESEARCH_PANEL_RECEIPT_ROOT",
        "V4_RESEARCH_PANEL_A_TDX_ROOT",
        "V4_RESEARCH_PANEL_HK_TDX_ROOT",
        "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "V4_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "V4_RESEARCH_PANEL_A_SEED_PANEL",
        "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "V4_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "V4_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "V4_RESEARCH_PANEL_A_SELECTOR_SEED",
        "V4_RESEARCH_PANEL_A_BACKTEST_SEED",
        "V4_RESEARCH_PANEL_A_CONTRACT_CSV",
        "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "V4_RESEARCH_PANEL_A_RETURN_ROOT",
        "V4_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
        "V4_RESEARCH_PANEL_HK_ASSET_ROOT",
    ):
        monkeypatch.setenv(
            name,
            str(receipt_root if name == "V4_RESEARCH_PANEL_RECEIPT_ROOT" else tmp_path / name.lower()),
        )
    monkeypatch.delenv("V4_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE", raising=False)
    if receipt_state != "missing":
        receipt_root.mkdir(parents=True)
        artifact_root = Path(os.environ["V4_RESEARCH_PANEL_HK_TDX_ROOT"]) / "vipdoc" / "ds" / "lday"
        artifact_root.mkdir(parents=True)
        artifact_path = artifact_root / "71#00001.day"
        artifact_path.write_bytes(b"hk-panel-fixture")
        artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        receipt_sha = hashlib.sha256(artifact_sha.encode()).hexdigest()
        row_count = 0 if receipt_state == "zero_metrics" else 1
        coverage_rate = 0.0 if receipt_state == "zero_metrics" else 1.0
        if receipt_state == "content_tampered":
            artifact_path.write_bytes(b"tampered-hk-panel-fixture")
        (receipt_root / "hk-20260821.json").write_text(
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_receipt.v1",
                    "lane": "HK",
                    "target_date": "20260821",
                    "status": "READY",
                    "row_count": row_count,
                    "file_count": 1,
                    "coverage_rate": coverage_rate,
                    "sha256": receipt_sha,
                    "files": [
                        {
                            "status": "READY",
                            "target_date": "20260821",
                            "row_count": 1,
                            "coverage_rate": 1.0,
                            "sha256": artifact_sha,
                            "path": str(artifact_path),
                            "production_allowed": False,
                            "buy_gate_updated": False,
                            "orders_sent": False,
                        }
                    ],
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            ),
            encoding="utf-8",
        )

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_authority_envelope.v1",
                    "lane": "HK",
                    "target_date": "20260821",
                    "status": "READY",
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        hk_0_2_python_executable=tmp_path / "hk02-python",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot="1720",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == "research_panel_daily_hk"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["lane_status"] == "CANNOT_CONFIRM"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["reason"] == "RESEARCH_PANEL_DAILY_LANE_NOT_READY"


def test_scheduler_recovers_a_fixed_minute_slot_after_a_300_second_wake(tmp_path: Path) -> None:
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 21, 9, 5, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        catchup_window_minutes=10,
    )

    assert due["slot"] == "0901"
    assert due["catchup"] is True
    assert due["lag_minutes"] == 4


def test_scheduler_fixed_slot_idempotency_blocks_second_catchup(tmp_path: Path) -> None:
    receipt = tmp_path / "receipts" / "live" / "20260821" / "0901" / "ok.dispatch-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-21T01:01:30Z"}),
        encoding="utf-8",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 21, 9, 5, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        catchup_window_minutes=10,
    )

    assert due["slot"] == "0900"
    assert due["catchup"] is True


def test_wechat_morning_probe_is_same_day_but_evening_sync_targets_next_trade_day() -> None:
    morning = scheduler.compute_dates(business_date="20260824", slot="0901")
    research_a = scheduler.compute_dates(business_date="20260824", slot="1700")
    research_hk = scheduler.compute_dates(business_date="20260824", slot="1720")
    evening = scheduler.compute_dates(business_date="20260824", slot="2001")

    assert morning["target_date"] == "20260824"
    assert research_a["target_date"] == "20260824"
    assert research_hk["target_date"] == "20260824"
    assert evening["target_date"] == "20260825"


def test_registry_dispatches_research_panel_evidence_to_fixed_entry(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del timeout_seconds
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "lanes": {
                        "A": {"status": "PARTIAL"},
                        "HK": {"status": "READY"},
                    }
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        selector_data_root=tmp_path / "selector",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot="1730",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "research_panel_runtime_evidence"
    )

    result = registry(workload, request)

    assert result["status"] == "SUCCEEDED"
    assert result["evidence_status"] == "PARTIAL"
    assert calls[0][0][1:4] == ["-m", "ops.publish_research_panel_runtime_receipt", "--date"]
    assert "--producer-receipt-root" in calls[0][0]
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_registry_dispatches_wechat_exact_pair_missing_is_retryable(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({"status": "CANNOT_CONFIRM", "cannot_confirm": ["WECHAT_EXACT_DATE_INPUT_MISSING"]}),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        preselection_input_root=tmp_path / "data" / "preselection_inputs",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="2001",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "wechat_preselection_sync"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["lane_status"] == "CANNOT_CONFIRM"
    assert result["target_date"] == "20260824"
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    argv = calls[0]
    assert argv[argv.index("--input-root") + 1] == str(tmp_path / "data" / "preselection_inputs")
    assert argv[argv.index("--data-root") + 1] != argv[argv.index("--input-root") + 1]


def test_wechat_sync_rejects_historical_pool_output_as_future_source(tmp_path: Path) -> None:
    def runner(command, *, cwd, timeout_seconds, env):
        del command, cwd, timeout_seconds, env
        raise AssertionError("rejected source must not invoke the sync module")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        preselection_input_root=tmp_path / "data" / "preselection_pools",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="0901",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "wechat_preselection_sync"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    assert raised.value.result["failure_class"] == "CONTRACT"
    assert "preselection_inputs" in raised.value.result["stderr"]


def test_registry_dispatches_review_core_partial_is_retryable(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '{"status":"PARTIAL","exit_code":2}', "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "shared-package",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="2115",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "review_core_pool_pipeline"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["pipeline_status"] == "PARTIAL"
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert calls[0][1:4] == ["-m", "ops.run_review_core_natural_pool_pipeline", "--trade-date"]


def test_retryable_wechat_receipt_retries_and_succeeds_after_exact_pair_ready(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    responses = iter(
        (
            subprocess.CompletedProcess(
                [],
                1,
                json.dumps({"status": "CANNOT_CONFIRM", "reason": "WECHAT_EXACT_DATE_INPUT_MISSING"}),
                "",
            ),
            subprocess.CompletedProcess([], 0, json.dumps({"status": "READY"}), ""),
        )
    )

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        response = next(responses)
        return subprocess.CompletedProcess(command, response.returncode, response.stdout, response.stderr)

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        runner=runner,
    )
    catalog = load_workload_catalog()
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="0901",
        mode=DispatchMode.LIVE,
    )
    ledger = ExecutionLedger(tmp_path / "ledger")

    first = dispatch_due(request, catalog, registry, ledger=ledger)
    assert first.status == "FAILED"
    assert first.failure_class == "UPSTREAM_NOT_READY"
    assert first.retry_after
    assert first.production_allowed is False
    assert first.buy_gate_updated is False
    assert first.orders_sent is False

    second = dispatch_due(request, catalog, registry, ledger=ledger)
    assert second.status == "SUCCEEDED"
    assert second.started_workload_ids == ("wechat_preselection_sync",)
    assert second.production_allowed is False
    assert second.buy_gate_updated is False
    assert second.orders_sent is False
    assert len(calls) == 2
