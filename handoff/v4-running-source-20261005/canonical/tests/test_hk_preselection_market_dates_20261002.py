from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("business_date", "a_target", "hk_target", "hk_signal", "hk_eligibility"),
    [
        ("20261002", "20261008", "20261005", "20261002", "20260930"),
        ("20261005", "20261008", "20261006", "20261005", "20260930"),
    ],
)
def test_hk_next_target_and_source_dates_follow_separate_calendars(
    business_date: str,
    a_target: str,
    hk_target: str,
    hk_signal: str,
    hk_eligibility: str,
) -> None:
    from contracts.trading_calendar import load_market_calendar, next_session
    from infrastructure.scheduling._executor_registry_parts.preselection import (
        _hk_next_target_date,
        _hk_preselection_source_dates,
    )

    calendar = load_market_calendar()
    assert next_session(calendar, business_date, market="a_share") == a_target
    assert _hk_next_target_date(business_date) == hk_target
    assert _hk_preselection_source_dates(business_date, hk_target) == (
        hk_signal,
        hk_eligibility,
    )


def test_normal_joint_open_day_keeps_a_and_hk_target_equal() -> None:
    from contracts.trading_calendar import load_market_calendar, next_session
    from infrastructure.scheduling._executor_registry_parts.preselection import (
        _hk_next_target_date,
        _hk_preselection_source_dates,
    )

    calendar = load_market_calendar()
    business_date = "20260925"
    common_target = next_session(calendar, business_date, market="a_share")
    assert common_target == "20260928"
    assert _hk_next_target_date(business_date) == common_target
    assert _hk_preselection_source_dates(business_date, common_target) == (
        business_date,
        "20260924",
    )


@pytest.mark.parametrize(
    ("business_date", "a_target", "hk_target", "hk_signal", "eligibility"),
    [
        ("20261002", "20261008", "20261005", "20261002", "20260930"),
        ("20261005", "20261008", "20261006", "20261005", "20260930"),
    ],
)
def test_preselection_owner_reads_and_materializes_exact_hk_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_date: str,
    a_target: str,
    hk_target: str,
    hk_signal: str,
    eligibility: str,
) -> None:
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling import executor_registry as registry_module
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    exact_reads: list[dict[str, str]] = []
    calls: list[tuple[str, list[str]]] = []
    verified = SimpleNamespace(
        run=SimpleNamespace(
            receipt={
                "status": "READY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            verification={
                "run_id": "hk-run-fixture",
                "artifact_sha256": "a" * 64,
                "row_count": 100,
            },
        )
    )

    def hk_reader(_root: Path, **kwargs):
        exact_reads.append(kwargs)
        return verified

    def isolated_loader(_root, *, module_leaf, **_kwargs):
        if module_leaf == "hk_0_2":
            return SimpleNamespace(read_verified_hk_0_2_pool=hk_reader)
        raise ModuleNotFoundError(module_leaf)

    def fake_runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append((str(command[2]), list(command[3:])))
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(
        registry_module, "load_isolated_package_module", isolated_loader
    )
    shared_root = tmp_path / "shared"
    (shared_root / "universes").mkdir(parents=True)
    (shared_root / "assets/hk_security_master").mkdir(parents=True)
    package_root = tmp_path / "package"
    scripts = package_root / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=shared_root,
        hk_universe_root=shared_root,
        shared_package_root=package_root,
        selector_data_root=tmp_path / "selector",
        preselection_input_root=tmp_path / "input",
        repo_root=Path(__file__).parents[1],
        runner=fake_runner,
        hk_0_2_python_executable=Path(sys.executable),
    )
    monkeypatch.setattr(registry, "_hk_0_2_runtime_error", lambda: None)
    request = DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=a_target,
        slot="1800",
        mode=DispatchMode.LIVE,
    )

    result = registry._preselection_pools(request)

    assert result["hk_target_date"] == hk_target
    assert result["hk_signal_date"] == hk_signal
    assert result["hk_eligibility_source_date"] == eligibility
    assert exact_reads == [
        {
            "target_date": hk_target,
            "expected_signal_date": hk_signal,
            "expected_eligibility_source_date": eligibility,
        }
    ]
    by_module = {module: args for module, args in calls}
    projection = by_module["ops.materialize_scheduled_preselection"]
    assert projection[projection.index("--trade-date") + 1] == a_target
    assert projection[projection.index("--hk-target-date") + 1] == hk_target
    assert projection[projection.index("--hk-signal-date") + 1] == hk_signal
    assert projection[projection.index("--hk-eligibility-source-date") + 1] == eligibility


def _strict_hk_pool(signal_date: str, target_date: str, eligibility_date: str):
    rows = [
        {
            "code_norm": f"{index:05d}",
            "rank": index,
            "score_prob_active": 1.0 - index / 1000,
            "signal_date": signal_date,
            "target_date": target_date,
            "d1_freshness_status": "PASS",
            "selected_strategy": "prob_active",
            "name": f"Fixture {index}",
        }
        for index in range(1, 101)
    ]
    verification = {
        "artifact_relative": f"runs/{target_date}/hk_top100.csv",
        "artifact_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "run_id": f"hk-run-{target_date}",
        "row_count": 100,
    }
    receipt = {
        "status": "READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest = {
        "provenance": {
            "signal_date": signal_date,
            "eligibility_source_date": eligibility_date,
            "security_master_trade_date": eligibility_date,
            "security_master_run_id": "security-master-20260930",
            "security_master_artifact_sha256": "d" * 64,
            "security_master_captured_at": "2026-09-30T17:20:06+08:00",
        }
    }
    return SimpleNamespace(
        rows=rows,
        run=SimpleNamespace(
            verification=verification,
            receipt=receipt,
            manifest=manifest,
        ),
    )


def test_scheduled_materializer_changes_only_hk_pool_date(tmp_path: Path) -> None:
    from ops.materialize_scheduled_preselection import build_scheduled_artifacts

    calls: list[dict[str, str]] = []

    def hk_reader(_root: Path, **kwargs):
        calls.append(kwargs)
        return _strict_hk_pool(
            kwargs["expected_signal_date"],
            kwargs["target_date"],
            kwargs["expected_eligibility_source_date"],
        )

    artifacts = build_scheduled_artifacts(
        trade_date="20261008",
        signal_date="20261002",
        hk_target_date="20261005",
        hk_signal_date="20261002",
        hk_eligibility_source_date="20260930",
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("A fixture unavailable")
        ),
        hk_pool_reader=hk_reader,
    )

    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    hk = by_id["hkconnect_d1_top100"]
    assert calls == [
        {
            "target_date": "20261005",
            "expected_signal_date": "20261002",
            "expected_eligibility_source_date": "20260930",
        }
    ]
    assert hk["trade_date"] == hk["target_date"] == "20261005"
    assert hk["signal_date"] == "20261002"
    assert hk["source_run_id"] == "hk-run-20261005"
    assert hk["source_manifest_sha256"] == "b" * 64
    assert len(hk["rows"]) == 100
    assert {
        artifact["trade_date"]
        for pool_id, artifact in by_id.items()
        if pool_id != "hkconnect_d1_top100"
    } == {"20261008"}
