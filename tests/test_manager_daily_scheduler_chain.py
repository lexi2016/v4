"""Focused scheduler-specific regression checks for the staged daily chain."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

from contracts import futu_us_boards
from infrastructure import research_peripheral_store
from ops._us_market_digest_parts import futu_boards
from v4.manager_workbench import service, supervisor, scheduler
from v4.manager_workbench import us_mapping_catalog
from v4.manager_workbench.inputs import native, source_bindings
from v4.manager_workbench.inputs.native import NativeAdapters


def test_scheduler_overlay_and_r2_hook_service_interfaces_are_preserved():
    overlay = Path(os.environ["V4_DAILY_CHAIN_SCHEDULER_OVERLAY"]).resolve()
    dependencies = Path(os.environ["V4_DAILY_CHAIN_SCHEDULER_DEPENDENCIES"]).resolve()
    support = Path(os.environ["V4_DAILY_CHAIN_SCHEDULER_SUPPORT"]).resolve()
    active_app = Path(os.environ["V4_DAILY_CHAIN_SCHEDULER_APP"]).resolve()

    for module in (native, source_bindings):
        assert Path(module.__spec__.origin).resolve().is_relative_to(overlay)
    for module in (service, supervisor, scheduler):
        assert Path(module.__file__).resolve().is_relative_to(active_app)
    for module in (us_mapping_catalog, research_peripheral_store, futu_boards, futu_us_boards):
        assert Path(module.__file__).resolve().is_relative_to(dependencies)

    assert hasattr(source_bindings, "_tdxpy_history_for_exact_parents")
    assert "_tdxpy_history_for_exact_parents" in inspect.getsource(source_bindings.resolve_bindings)
    assert "start" in inspect.signature(supervisor.WorkbenchHook.from_environment).parameters
    assert "submit" in dir(service.ManagerService)
    submit = inspect.signature(service.ManagerService.submit)
    assert {"target_date", "phase", "lanes", "cutoff", "scope_refs"}.issubset(submit.parameters)
    assert callable(scheduler.tick)
    assert "start" in inspect.signature(supervisor.WorkbenchHook.from_environment).parameters

    allowed = (overlay, dependencies, support, active_app)
    for name, module in tuple(__import__("sys").modules.items()):
        if not (name == "infrastructure" or name.startswith(("infrastructure.", "contracts.", "ops.", "v4.manager_workbench"))):
            continue
        path = getattr(module, "__file__", None)
        if path:
            resolved = Path(path).resolve()
            assert any(resolved.is_relative_to(root) for root in allowed), (name, resolved)
