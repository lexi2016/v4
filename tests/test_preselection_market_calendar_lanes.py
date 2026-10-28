from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("trade_date", "target_date", "eligible_a", "eligible_hk"),
    [
        ("20260925", "20260928", False, True),
        ("20261007", "20261008", False, True),
        ("20260403", "20260407", True, False),
        ("20260924", "20260925", True, True),
        ("20260217", "20260220", False, False),
    ],
)
def test_preselection_admission_and_task_status_use_a_or_hk_securities(
    trade_date: str,
    target_date: str,
    eligible_a: bool,
    eligible_hk: bool,
) -> None:
    from contracts.runtime_tasks import SessionRequirement
    from contracts.trading_calendar import MarketScope, RunPolicy
    from domains.runtime_policy import evaluate_run_policy
    from domains.task_status import _schedule_date_is_eligible
    from infrastructure.scheduling.catalog import load_workload_catalog

    catalog = load_workload_catalog()
    workload = next(item for item in catalog.workloads if item.workload_id == "preselection_pools")

    assert workload.run_policy is RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY
    assert workload.market_scope is MarketScope.CROSS_MARKET
    decision = evaluate_run_policy(
        workload.run_policy,
        trade_date,
        workload.slots[0],
        market_scope=workload.market_scope,
        session_requirement=SessionRequirement(workload.session_requirement),
    )
    expected = tuple(
        market
        for market, eligible in (("a_share", eligible_a), ("hk_securities", eligible_hk))
        if eligible
    )

    assert decision.eligible is bool(expected)
    assert decision.eligible_markets == expected
    assert _schedule_date_is_eligible(workload, trade_date) is bool(expected)
    if expected:
        assert decision.trade_date == trade_date
    else:
        assert decision.reason == "NON_TRADING_DAY"


@pytest.mark.parametrize(
    ("trade_date", "target_date", "eligible_a", "eligible_hk"),
    [
        ("20260925", "20260928", False, True),
        ("20261007", "20261008", False, True),
        ("20260403", "20260407", True, False),
        ("20260924", "20260925", True, True),
        ("20260217", "20260220", False, False),
    ],
)
def test_original_preselection_owner_runs_only_open_market_lanes(
    trade_date: str,
    target_date: str,
    eligible_a: bool,
    eligible_hk: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling import executor_registry as registry_module
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    calls: list[str] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        module = str(command[2])
        calls.append(module)
        if module == "ops.materialize_scheduled_preselection":
            arguments = list(command[3:])
            market_scope = arguments[arguments.index("--market-scope") + 1]
            required = {}
            if market_scope in {"A_SHARE", "CROSS_MARKET"}:
                required["a_d1_premarket_pool"] = {
                    "status": "V192_CANDIDATE_READY",
                    "row_count": 1,
                    "ready": True,
                }
            if market_scope in {"HK_CONNECT", "CROSS_MARKET"}:
                required["hkconnect_d1_top100"] = {
                    "status": "STRICT_0_2_READY",
                    "row_count": 100,
                    "ready": True,
                }
            payload = {
                "status": "READY",
                "formal_pool_gate": {
                    "status": "READY",
                    "market_scope": market_scope,
                    "required": required,
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        registry_module,
        "load_isolated_package_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ModuleNotFoundError("fixture")),
    )
    selector = tmp_path / "selector.csv"
    selector.write_text("ts_code\n000001.SZ\n", encoding="utf-8")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args, **_kwargs: selector)

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
        scheduled_date=trade_date,
        business_date=trade_date,
        target_date=target_date,
        slot="1800",
        mode=DispatchMode.LIVE,
    )

    if not (eligible_a or eligible_hk):
        from infrastructure.scheduling.executor_registry import WorkloadExecutionError

        with pytest.raises(WorkloadExecutionError) as raised:
            registry._preselection_pools(request)
        assert raised.value.result["status"] == "FAILED"
        assert raised.value.result["exit_code"] == 1
        assert "ops.materialize_scheduled_preselection" not in calls
        assert not {
            "scripts.capture_public_fupan",
            "ops.materialize_shared_v192_preselection",
            "scripts.update_hk_0_2_panel",
            "ops.ensure_hk_security_master",
            "scripts.materialize_hk_0_2",
        }.intersection(calls)
        return

    result = registry._preselection_pools(request)

    expected_a_modules = {
        "scripts.capture_public_fupan",
        "ops.materialize_shared_v192_preselection",
        "ops.materialize_d1_review_lanes",
    }
    expected_hk_modules = {
        "scripts.update_hk_0_2_panel",
        "ops.ensure_hk_security_master",
        "scripts.materialize_hk_0_2",
    }
    assert expected_a_modules.issubset(calls) is eligible_a
    assert expected_hk_modules.issubset(calls) is eligible_hk
    assert "ops.materialize_scheduled_preselection" in calls
    assert result["a_lane_status"] == ("SUCCEEDED" if eligible_a else "NOT_APPLICABLE")
    assert result["hk_lane_status"] == ("SUCCEEDED" if eligible_hk else "NOT_APPLICABLE")
