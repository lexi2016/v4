from contextlib import contextmanager
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest


_HELPER_SYMBOLS = {
    "executor_registry_common": (
        "_audited_peripheral_degradation",
        "_audited_peripheral_timeout_reuse",
        "_bounded",
        "_collector_not_materialized_result",
        "_default_runner",
    ),
    "executor_registry_research": (
        "_repair_requested",
        "_repair_collector_arguments",
        "_hourly_research",
        "_us_market_digest",
        "_zsxq_0830",
        "_morning_news_0830",
        "_research_preselection_refresh",
        "_baimao_x_refresh",
        "_stage_workbench",
        "_hk_auction_0920",
    ),
    "executor_registry_preselection": (
        "_verified_formal_pool_reuse",
        "_preselection_pools",
    ),
    "executor_registry_review": (
        "_daily_materialize",
        "_decoded_stdout",
        "_safe_lane_status",
        "_research_panel_runtime_evidence",
        "_research_panel_daily",
        "_wechat_preselection_sync",
        "_review_core_pool_pipeline",
        "_run_stage_center_milestone",
        "_run_close_review_node",
        "_a_share_close_review",
        "_hk_connect_close_review",
    ),
}


def _unused_helper(*_args, **_kwargs):
    return None


def _load_registry_api(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "infrastructure/scheduling/executor_registry.py"
    namespace = f"_dispatch_source_wait_isolated_{id(source):x}"
    package = ModuleType(namespace)
    package.__path__ = [str(source.parent)]
    runtime_graph = importlib.import_module("infrastructure.runtime_graph")
    sentinel = object()
    previous_notifications = getattr(runtime_graph, "notifications", sentinel)

    with monkeypatch.context() as isolated:
        isolated.setitem(sys.modules, namespace, package)
        for module_name, names in _HELPER_SYMBOLS.items():
            module = ModuleType(f"{namespace}.{module_name}")
            for name in names:
                setattr(module, name, _unused_helper)
            isolated.setitem(sys.modules, module.__name__, module)

        notifications = ModuleType("infrastructure.runtime_graph.notifications")
        notifications.notify = _unused_helper
        isolated.setitem(sys.modules, notifications.__name__, notifications)

        module_name = f"{namespace}.executor_registry"
        spec = importlib.util.spec_from_file_location(module_name, source)
        module = importlib.util.module_from_spec(spec)
        isolated.setitem(sys.modules, module_name, module)
        try:
            spec.loader.exec_module(module)
        finally:
            if previous_notifications is sentinel:
                runtime_graph.__dict__.pop("notifications", None)
            else:
                runtime_graph.notifications = previous_notifications

    assert not any(
        name == namespace or name.startswith(namespace + ".") for name in sys.modules
    )
    return module.FixedExecutorRegistry, module.WorkloadExecutionError


@contextmanager
def _fake_derivative_stack(monkeypatch, governed_calls):
    ops_package = importlib.import_module("ops")
    top200 = ModuleType("ops.research_panel_top200")

    def complete_daily_derivatives(*args):
        if args[-1] is not None:
            raise ValueError("UPSTREAM_DAILY_SOURCE_FAILED")
        return {"status": "SUCCEEDED", "data_date": "20261113"}

    top200.complete_daily_derivatives = complete_daily_derivatives
    governance = ModuleType("ops.research_storage_governance")

    def governed_product(function, *args):
        governed_calls.append(args[-1])
        if args[-1] is not None:
            # Reproduce R1's observed ordering: SourceContext rejects the old
            # active pair before complete_daily_derivatives checks its guard.
            raise ValueError("DAILY_PAIRED_GENERATION_OR_DATE_CONFLICT")
        return function(*args)

    governance.governed_product = governed_product
    with monkeypatch.context() as isolated:
        isolated.setitem(sys.modules, top200.__name__, top200)
        isolated.setitem(sys.modules, governance.__name__, governance)
        isolated.setattr(ops_package, "research_panel_top200", top200, raising=False)
        isolated.setattr(ops_package, "research_storage_governance", governance, raising=False)
        yield


def _live_request():
    return SimpleNamespace(
        business_date="20261113",
        mode=SimpleNamespace(value="LIVE"),
        slot="1540",
    )


def _registry(monkeypatch, tmp_path):
    registry_type, error_type = _load_registry_api(monkeypatch)
    for name, value in {
        "V4_A_SHARE_DAILY_PRODUCT_ROOT": tmp_path / "products",
        "V4_RESEARCH_PANEL_A_DATA_ROOT": tmp_path / "data",
        "V4_RESEARCH_PANEL_RECEIPT_ROOT": tmp_path / "receipts",
        "V4_WORKBENCH_CLASSIFICATION_ROOT": tmp_path / "classification",
    }.items():
        monkeypatch.setenv(name, str(value))
    return object.__new__(registry_type), error_type


def test_failed_source_wait_keeps_original_exception_and_retry_identity(
    monkeypatch, tmp_path
):
    governed_calls = []
    registry, error_type = _registry(monkeypatch, tmp_path)
    original_result = {
        "workload_id": "research_panel_daily_a",
        "status": "FAILED",
        "failure_class": "UPSTREAM_NOT_READY",
        "reason": "SOURCE_NOT_READY",
        "retry_identity": "a-daily:20261113:1540:source-attempt-2",
        "exit_code": 1,
    }
    original_error = error_type(original_result)

    def failed_source(_request):
        raise original_error

    monkeypatch.setattr(registry, "_run_a_daily_source", failed_source)

    with _fake_derivative_stack(monkeypatch, governed_calls):
        with pytest.raises(error_type) as raised:
            registry._run_a_daily(_live_request())

    assert raised.value is original_error
    assert raised.value.result is original_result
    assert raised.value.result["reason"] == "SOURCE_NOT_READY"
    assert raised.value.result["retry_identity"] == "a-daily:20261113:1540:source-attempt-2"
    assert governed_calls == []


def test_returned_failed_source_result_is_preserved_without_derivatives(
    monkeypatch, tmp_path
):
    governed_calls = []
    registry, _error_type = _registry(monkeypatch, tmp_path)
    source_result = {
        "workload_id": "research_panel_daily_a",
        "status": "FAILED",
        "reason": "SOURCE_NOT_READY",
        "retry_identity": "a-daily:20261113:1540:source-attempt-2",
    }
    monkeypatch.setattr(registry, "_run_a_daily_source", lambda _request: source_result)

    with _fake_derivative_stack(monkeypatch, governed_calls):
        result = registry._run_a_daily(_live_request())

    assert result is source_result
    assert result["reason"] == "SOURCE_NOT_READY"
    assert result["retry_identity"] == "a-daily:20261113:1540:source-attempt-2"
    assert governed_calls == []


def test_successful_same_day_resume_still_runs_derivatives(monkeypatch, tmp_path):
    governed_calls = []
    registry, _error_type = _registry(monkeypatch, tmp_path)
    resumed_source_result = {
        "workload_id": "research_panel_daily_a",
        "status": "SUCCEEDED",
        "migration_reuse": True,
        "provider_invoked": False,
        "target_date": "20261113",
    }
    monkeypatch.setattr(
        registry, "_run_a_daily_source", lambda _request: resumed_source_result
    )

    with _fake_derivative_stack(monkeypatch, governed_calls):
        result = registry._run_a_daily(_live_request())

    assert result["migration_reuse"] is True
    assert result["provider_invoked"] is False
    assert result["daily_derivatives"] == {
        "status": "SUCCEEDED",
        "data_date": "20261113",
    }
    assert governed_calls == [None]
