"""Unit harness for Issue32 source slices, not the absent active application.

Imports that are absent from the supplied current-owner bundle are explicitly
stubbed here. Child process calls are a deterministic boundary: tests exercise
the supplied handler and dispatcher decisions, not HK data production, release
identity, a real calendar, or the unavailable execution ledger implementation.
"""
from __future__ import annotations

import builtins
from dataclasses import dataclass
from enum import Enum
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("ISSUE32_SCHEDULER_SOURCE_ROOT", str(ROOT / "after")))


class Policy(Enum):
    NATURAL_DAY = "NATURAL_DAY"
    A_OR_HK_CONNECT_TRADE_DAY = "A_OR_HK_CONNECT_TRADE_DAY"


class DayState(Enum):
    FULL_TRADING_DAY = "FULL_TRADING_DAY"
    HALF_TRADING_DAY_AM = "HALF_TRADING_DAY_AM"
    NON_TRADING_DAY = "NON_TRADING_DAY"


class WorkloadExecutionError(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__("workload execution failed")


def module_stub(monkeypatch, name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def load_file(monkeypatch, relative, prefix="issue32_slice"):
    name = f"{prefix}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SOURCE / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def request():
    return SimpleNamespace(
        business_date="20261008", scheduled_date="20261008",
        target_date="20261009", slot="1730", mode=SimpleNamespace(value="LIVE"),
    )


def workload(workload_id="preselection_pools"):
    return SimpleNamespace(
        workload_id=workload_id, enabled=True, slots=("1730", "1800"),
        run_policy=Policy.A_OR_HK_CONNECT_TRADE_DAY,
        market_scope="CROSS_MARKET", session_requirement="DAY_ELIGIBILITY_ONLY",
        non_trading_day_slots=(), scheduled_date_role="SCHEDULED_DATE",
        signal_date_role="BUSINESS_DATE", target_date_role="TARGET_DATE",
    )


def catalog(*items):
    return SimpleNamespace(
        safety=SimpleNamespace(production_allowed=False, buy_gate_updated=False, orders_sent=False),
        workloads=items or (workload(),),
    )


def common_stubs(monkeypatch):
    module_stub(monkeypatch, "contracts.runtime_tasks", DispatchMode=object,
                DispatchRequest=object, RuntimeCatalog=object, WorkloadDefinition=object)
    module_stub(
        monkeypatch, "contracts.trading_calendar", RunPolicy=Policy,
        MarketScope=SimpleNamespace(CROSS_MARKET="CROSS_MARKET"),
        SessionRequirement=SimpleNamespace(DAY_ELIGIBILITY_ONLY="DAY_ELIGIBILITY_ONLY"),
        TradingDayState=DayState, load_market_calendar=lambda: None,
        previous_session=lambda calendar, day, **kwargs: "20261008",
        next_session=lambda calendar, day, **kwargs: "20261009",
        resolve_market_states=lambda *args: {
            "a_share": DayState.FULL_TRADING_DAY,
            "hk_securities": DayState.FULL_TRADING_DAY,
            "hk_connect": DayState.FULL_TRADING_DAY,
        },
    )


def load_dispatcher(monkeypatch, owner):
    common_stubs(monkeypatch)
    module_stub(monkeypatch, "domains.runtime_policy", RunDecision=object,
                evaluate_run_policy=lambda *args, **kwargs: SimpleNamespace(
                    eligible=True, reason="ELIGIBLE", eligible_markets=("A", "HK"), blocked_markets=()))
    module_stub(monkeypatch, "infrastructure.scheduling.execution_ledger", ExecutionLedger=object)
    module_stub(monkeypatch, "infrastructure.scheduling.executor_registry",
                WorkloadExecutionError=WorkloadExecutionError)
    if owner == "canonical_reference":
        module_stub(monkeypatch, "infrastructure.scheduling", manager_capture_retry=SimpleNamespace())
        module_stub(monkeypatch, "infrastructure.owned_io", SafeRoot=object)
    module = load_file(monkeypatch, f"source/{owner}/infrastructure/scheduling/dispatcher.py")
    if owner == "canonical_reference":
        # These are receipt/control-flow tests. The actual release identity
        # closure is absent and remains a separate Mac integration requirement.
        monkeypatch.setattr(module, "validate_release_identity", lambda: {"release_id": "unit-only"})
    return module


def load_preselection(monkeypatch, owner):
    common_stubs(monkeypatch)
    module_stub(monkeypatch, "infrastructure.preselection_pool_store", PreselectionPoolStore=object)
    module_stub(monkeypatch, "ops.daily_materialize", resolve_selector_panel=lambda root, day: root / "panel.csv")
    if owner == "actual_pool_scheduler":
        module = load_file(monkeypatch, "source/actual_pool_scheduler/infrastructure/scheduling/executor_registry_preselection.py")
        module.WorkloadExecutionError = WorkloadExecutionError
        module._default_runner = object()
        module._V192_PRESELECTION_TIMEOUT_SECONDS = 1800
        return module, module._preselection_pools
    namespace = "issue32_split_harness"
    package = module_stub(monkeypatch, namespace)
    package.__path__ = []
    module_stub(monkeypatch, f"{namespace}._namespace", read_global=lambda scope, key: scope.get(key, getattr(builtins, key, None)))
    name = f"{namespace}.preselection"
    spec = importlib.util.spec_from_file_location(name, SOURCE / "source/canonical_reference/infrastructure/scheduling/_executor_registry_parts/preselection.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    def missing_source(*args, **kwargs):
        raise FileNotFoundError("exact source absent in unit fixture")

    scope = {
        "Path": Path, "os": os, "WorkloadExecutionError": WorkloadExecutionError,
        "_default_runner": object(), "_V192_PRESELECTION_TIMEOUT_SECONDS": 1800,
        "resolve_selector_panel": lambda root, day: root / "panel.csv",
        "load_isolated_package_module": missing_source,
    }
    return module, lambda registry, req: module._FixedExecutorRegistry__preselection_pools_body(scope, registry, req)


def success(**extra):
    return dict(status="SUCCEEDED", exit_code=0, stdout="", stderr="",
                production_allowed=False, buy_gate_updated=False, orders_sent=False, **extra)


class ProcessBoundary:
    """A fake child boundary; it never creates financial or authoritative data."""
    def __init__(self, root, failing_module=None, optional_failure=False):
        self.root = root
        self.shared_data_root = root / "shared"
        self.shared_package_root = root / "package"
        self.hk_universe_root = self.shared_data_root
        self.repo_root = root / "app"
        self.preselection_input_root = root / "inputs"
        self.data_root = root / "local"
        self.selector_data_root = root / "selector"
        self.shared_futu_python_executable = root / "python"
        self.hk_0_2_python_executable = root / "hkpython"
        self.hk_0_2_tdx_root = root / "tdx"
        self.stage_selection_root = None
        self._runner = object()
        self.calls = []
        self.failing_module = failing_module
        self.optional_failure = optional_failure
        self.scored = root / "unit-scorer-invoked.txt"
        self.local_materialized = root / "unit-local-materializer-invoked.txt"
        for directory in (self.shared_data_root / "universes", self.shared_data_root / "assets/hk_security_master", self.repo_root / "ops", self.shared_package_root / "scripts", self.selector_data_root):
            directory.mkdir(parents=True, exist_ok=True)
        for leaf in ("capture_public_fupan.py", "materialize_v192_selector.py", "update_hk_0_2_panel.py", "materialize_hk_0_2.py"):
            (self.shared_package_root / "scripts" / leaf).touch()
        (self.repo_root / "ops/ensure_hk_security_master.py").touch()
        (self.selector_data_root / "panel.csv").touch()

    def _verified_formal_pool_reuse(self, day):
        return None

    def _verified_preselection_source(self, **kwargs):
        return None, "unit exact source absent"

    def _hk_0_2_runtime_error(self):
        return None

    def _failure_result(self, workload_id, modules, message):
        return dict(status="FAILED", workload_id=workload_id, modules=modules,
                    exit_code=1, stderr=message, stdout="",
                    production_allowed=False, buy_gate_updated=False, orders_sent=False)

    def _decoded_stdout(self, result):
        # Match the supplied canonical facade's literal JSON-object contract.
        try:
            payload = json.loads(str(result.get("stdout") or ""))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _run(self, module, arguments, **kwargs):
        self.calls.append((module, list(arguments)))
        if module == "scripts.materialize_hk_0_2":
            self.scored.write_text("unit boundary invoked")
        if module == "ops.materialize_scheduled_preselection":
            self.local_materialized.write_text("A/local materialization allowed")
            payload = {"formal_pool_gate": {"required": {
                "a_d1_premarket_pool": {"ready": True},
                "hkconnect_d1_top100": {"ready": self.failing_module is None},
            }}}
            return {
                **success(), "stdout": json.dumps(payload), "_authoritative_payload": payload,
            }
        if module == self.failing_module or (self.optional_failure and module == "ops.materialize_d1_review_lanes"):
            return self._failure_result("preselection_pools", [module], f"EXACT_INPUT_MISSING:{module}:20261008")
        return success()


@dataclass
class Claim:
    acquired: bool
    run_id: str


class LedgerBoundary:
    """Records dispatcher API usage; it is not the real ledger implementation."""
    def __init__(self, root, settled=()):
        self.root = root
        self.settled = set(settled)
        self.receipts = [{"slot": "0925", "status": "SUCCEEDED", "run_id": "old-terminal"}]
        self.released = []

    def list_receipts(self, date, mode):
        return list(self.receipts)

    def try_claim_dispatch(self, req):
        return Claim(True, "new-attempt")

    def try_claim_workload(self, req, work, *, run_id):
        return Claim(work.workload_id not in self.settled, run_id)

    def receipt_relative(self, req, *, run_id):
        return f"{run_id}.json"

    def write_receipt(self, relative, payload):
        self.receipts.append(payload)

    def release_failed_request(self, req, *, run_id, workload_ids):
        self.released.append((run_id, workload_ids))
