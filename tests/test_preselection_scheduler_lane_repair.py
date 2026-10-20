"""Offline tests against retained scheduler facade; two reviewed modules overlaid in memory."""
from __future__ import annotations
import importlib
import importlib.util
import ast
import argparse
import inspect
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("HK_TOP100_RUNTIME_ROOT", "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-mapping-close-scheduler-20261020-r1/app"))
SHARED = Path(os.environ.get("HK_TOP100_SHARED_ROOT", "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r4/app/upstreams/v3_shared_data"))
BASELINE = os.environ.get("HK_TOP100_BASELINE") == "1"
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent_name, _, attribute = name.rpartition(".")
    if parent_name in sys.modules:
        setattr(sys.modules[parent_name], attribute, module)
    return module

@pytest.fixture
def runtime():
    import infrastructure.scheduling
    assert Path(infrastructure.scheduling.__file__).resolve().is_relative_to(RUNTIME)
    p = "infrastructure/scheduling/executor_registry_preselection.py"
    preselection = load("infrastructure.scheduling.executor_registry_preselection", (RUNTIME if BASELINE else SOURCE) / p)
    import infrastructure.scheduling.executor_registry as facade
    facade = importlib.reload(facade)
    p = "ops/materialize_scheduled_preselection.py"
    materializer = load("ops.materialize_scheduled_preselection", (RUNTIME if BASELINE else SOURCE / "docs/handoffs/hk_top100_holiday_20261020/runtime_overlay") / p)
    return facade, preselection, materializer

def request(business="20261019", target="20261020"):
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    return DispatchRequest(scheduled_date=business, business_date=business, target_date=target, slot="1730", mode=DispatchMode.LIVE)

def registry_fixture(runtime, tmp_path, monkeypatch, reuse=None):
    facade = runtime[0]
    package = tmp_path / "package"
    (package / "scripts").mkdir(parents=True)
    for name in ("capture_public_fupan", "materialize_v192_selector", "update_hk_0_2_panel", "materialize_hk_0_2"):
        (package / "scripts" / (name + ".py")).write_text("# fixture\n")
    repo = tmp_path / "repo"
    (repo / "ops").mkdir(parents=True)
    (repo / "ops/ensure_hk_security_master.py").write_text("# fixture\n")
    shared = tmp_path / "shared"
    (shared / "universes").mkdir(parents=True)
    (shared / "assets/hk_security_master").mkdir(parents=True)
    registry = facade.FixedExecutorRegistry(data_root=tmp_path / "data", shared_data_root=shared, shared_package_root=package,
        hk_universe_root=shared, preselection_input_root=tmp_path / "inputs", selector_data_root=tmp_path / "selector", repo_root=repo, runner=lambda *a, **k: None)
    monkeypatch.setattr(registry, "_verified_formal_pool_reuse", lambda date: reuse)
    monkeypatch.setattr(registry, "_hk_0_2_runtime_error", lambda: None)
    monkeypatch.setattr(facade, "resolve_selector_panel", lambda root, date: root / (date + ".csv"))
    calls = []
    def run(module, arguments, **kwargs):
        calls.append((module, list(arguments), kwargs))
        gate = {"required": {"a_d1_premarket_pool": {"ready": True}, "hkconnect_d1_top100": {"ready": True}}}
        return {"status": "SUCCEEDED", "exit_code": 0, "stdout": "", "stderr": "", "_authoritative_payload": {"formal_pool_gate": gate}, **FLAGS}
    monkeypatch.setattr(registry, "_run", run)
    return registry, calls

def argument(calls, module, flag):
    args = next(args for name, args, kw in calls if name == module)
    return args[args.index(flag) + 1]

@pytest.mark.skipif(not BASELINE, reason="retained-runtime reproduction")
def test_baseline_normal_uses_hk_holiday(runtime, tmp_path, monkeypatch):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    registry._preselection_pools(request())
    assert argument(calls, "scripts.update_hk_0_2_panel", "--through-date") == "20261019"
    assert argument(calls, "ops.ensure_hk_security_master", "--trade-date") == "20261019"
    assert argument(calls, "scripts.materialize_hk_0_2", "--signal-date") == "20261019"

@pytest.mark.skipif(not BASELINE, reason="retained-runtime reproduction")
def test_baseline_retry_missing_facade_helper(runtime, tmp_path, monkeypatch):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch, reuse={"hk_missing_retry": True, "a_identity": {"sha": "a"}})
    with pytest.raises(NameError, match="_retry_missing_hk_only"):
        registry._preselection_pools(request())
    assert calls == []

@pytest.mark.skipif(BASELINE, reason="overlay regression")
@pytest.mark.parametrize("business,target,signal,eligibility", [
    ("20261019", "20261020", "20261016", "20261016"), ("20261020", "20261021", "20261020", "20261020"),
    ("20260930", "20261008", "20260930", "20260930")])
def test_actual_facade_normal_dates_and_a_unchanged(runtime, tmp_path, monkeypatch, business, target, signal, eligibility):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    result = registry._preselection_pools(request(business, target))
    hk_target = runtime[1]._hk_next_target_date(business)
    assert result["status"] == "SUCCEEDED"
    assert argument(calls, "scripts.update_hk_0_2_panel", "--through-date") == signal
    assert argument(calls, "ops.ensure_hk_security_master", "--trade-date") == eligibility
    assert argument(calls, "scripts.materialize_hk_0_2", "--signal-date") == signal
    assert argument(calls, "scripts.materialize_hk_0_2", "--target-date") == hk_target
    scorer_arguments = next(args for name, args, kw in calls if name == "scripts.materialize_hk_0_2")
    assert retained_cli_parser().parse_args(scorer_arguments).signal_date == signal
    assert argument(calls, "ops.materialize_scheduled_preselection", "--signal-date") == business
    assert argument(calls, "ops.materialize_scheduled_preselection", "--trade-date") == target
    assert argument(calls, "ops.materialize_scheduled_preselection", "--hk-signal-date") == signal
    assert argument(calls, "ops.materialize_scheduled_preselection", "--hk-eligibility-source-date") == eligibility
    assert argument(calls, "ops.materialize_shared_v192_preselection", "--signal-date") == business
    assert all(result[key] is False for key in FLAGS)

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_actual_facade_hk_only_retry(runtime, tmp_path, monkeypatch):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch, reuse={"hk_missing_retry": True, "a_identity": {"sha": "a"}})
    received = []
    monkeypatch.setattr(runtime[1], "_retry_missing_hk_only", lambda self, req, **kw: received.append(kw) or {"status": "SUCCEEDED", **FLAGS})
    assert registry._preselection_pools(request())["status"] == "SUCCEEDED"
    assert received == [dict(signal_date="20261016", target_date="20261020", eligibility_source_date="20261016", a_identity={"sha": "a"})]
    assert calls == []

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_unknown_calendar_stops_before_producer(runtime, tmp_path, monkeypatch):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    with pytest.raises(runtime[0].WorkloadExecutionError):
        registry._preselection_pools(request("20270104", "20270105"))
    assert calls == []

def source_pool(signal, target):
    rows = [dict(code_norm=f"{n:05d}", rank=n, score_prob_active=1 - n / 1000, signal_date=signal, target_date=target,
        d1_freshness_status="PASS", selected_strategy="prob_active", history_resolution_identity="e" * 64, **FLAGS) for n in range(1, 101)]
    verification = dict(status="READY", artifact_sha256="a" * 64, manifest_sha256="b" * 64, receipt_sha256="c" * 64,
        run_id="fixture-run", row_count=100, artifact_relative="fixture.json")
    return SimpleNamespace(rows=rows, run=SimpleNamespace(verification=verification, receipt={"status": "READY", **FLAGS}, manifest={}))

@pytest.mark.skipif(BASELINE, reason="overlay regression")
@pytest.mark.parametrize("business,target,signal,eligibility", [
    ("20261019", "20261020", "20261016", "20261016")])
def test_real_mapper_and_gate_bind_hk_reader(runtime, tmp_path, monkeypatch, business, target, signal, eligibility):
    materializer = runtime[2]
    calls = []
    pool = source_pool(signal, target)
    signature = retained_reader_signature()
    def reader(root, *, target_date, expected_signal_date):
        signature.bind(root, target_date=target_date, expected_signal_date=expected_signal_date)
        calls.append(dict(target_date=target_date, expected_signal_date=expected_signal_date))
        assert target_date == target and expected_signal_date == signal
        return pool
    monkeypatch.setattr(materializer, "build_hourly_research_pool", lambda *a, **kw: {})
    monkeypatch.setattr(materializer, "load_baimao_preselection_pool", lambda *a, **kw: {})
    a_pool = {"pool_id": "a_d1_premarket_pool", "status": "V192_CANDIDATE_READY", "rows": [{"code": "000001"}]}
    artifacts = materializer.build_scheduled_artifacts(trade_date="20261008" if business == "20261002" else target,
        signal_date=business, selector=None, input_root=tmp_path / "inputs", data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared", shared_package_root=tmp_path / "package", hk_pool_reader=reader,
        reuse_formal_pools={"a_d1_premarket_pool": a_pool})
    hk = next(a for a in artifacts if a.get("pool_id") == "hkconnect_d1_top100")
    assert hk["status"] == "STRICT_0_2_READY" and len(hk["rows"]) == 100
    assert hk["trade_date"] == target and hk["signal_date"] == signal
    assert materializer._formal_pool_gate(artifacts)["required"]["hkconnect_d1_top100"]["ready"] is True
    assert calls and artifacts[0] == a_pool

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_consumer_rejects_holiday_override_before_read_or_write(runtime, tmp_path):
    reads = []
    with pytest.raises(ValueError, match="frozen calendar"):
        runtime[2].build_scheduled_artifacts(trade_date="20261020", signal_date="20261019", selector=None,
            input_root=tmp_path, data_root=tmp_path, shared_data_root=tmp_path, shared_package_root=tmp_path,
            hk_signal_date="20261019", hk_pool_reader=lambda *a, **kw: reads.append(kw))
    assert reads == []

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_reused_formal_gate_rejects_unsupported_split_before_reader(runtime, tmp_path, monkeypatch):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    import infrastructure.isolated_package_loader as loader
    pool = source_pool("20261002", "20261005")
    received = []
    def reader(root, **kw):
        received.append(kw)
        return pool
    monkeypatch.setattr(loader, "load_isolated_package_module", lambda *a, **kw: SimpleNamespace(read_verified_hk_0_2_pool=reader))
    a = dict(pool_id="a_d1_premarket_pool", market="A", trade_date="20261005", target_date="20261005", source_role="SHARED_VERIFIED_V192",
        stage_selection_eligible=True, status="READY", rows=[{"code": "000001"}], **FLAGS)
    hk = dict(pool_id="hkconnect_d1_top100", market="HK", trade_date="20261005", target_date="20261005", signal_date="20261002",
        source_role="SHARED_VERIFIED_HK_0_2", stage_selection_eligible=True, status="STRICT_0_2_READY", source_sha256="a" * 64,
        source_manifest_sha256="b" * 64, source_receipt_sha256="c" * 64, source_run_id="fixture-run",
        rows=[dict(row, code=row["code_norm"], pool_score=row["score_prob_active"]) for row in pool.rows], **FLAGS)
    monkeypatch.setattr(PreselectionPoolStore, "read_pool", lambda self, date, pool_id: a if pool_id == a["pool_id"] else hk)
    registry = runtime[0].FixedExecutorRegistry(data_root=tmp_path, shared_data_root=tmp_path, shared_package_root=tmp_path)
    result = registry._verified_formal_pool_reuse("20261005")
    assert result["status"] == "FAILED" and result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["reason"] == "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
    assert received == []

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_evidence_failure_does_not_block_preselection(runtime):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.catalog import load_workload_catalog
    catalog = load_workload_catalog(RUNTIME / "contracts/runtime_workloads.json")
    selected = ("research_panel_runtime_evidence", "preselection_pools")
    catalog = replace(catalog, workloads=tuple(w for w in catalog.workloads if w.workload_id in selected))
    called = []
    def executor(workload, req, decision):
        called.append(workload.workload_id)
        if workload.workload_id == "research_panel_runtime_evidence":
            raise runtime[0].WorkloadExecutionError({"status": "FAILED", "stderr": "PRODUCER_RECEIPT_MISSING:HK:20261019"})
        return {"status": "SUCCEEDED", **FLAGS}
    result = dispatch_due(request(), catalog, executor)
    assert called == list(selected)
    assert "preselection_pools" in result.started_workload_ids
    assert result.status == "FAILED"

@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_candidate_split_prepares_hk_on_a_open_hk_holiday(runtime, tmp_path, monkeypatch):
    import types
    import contracts
    # Candidate split is verified with its own unchanged candidate calendar.
    original_calendar = sys.modules["contracts.trading_calendar"]
    candidate_calendar = load("contracts.trading_calendar", SOURCE / "contracts/trading_calendar.py")
    monkeypatch.setitem(sys.modules, "contracts.trading_calendar", candidate_calendar)
    monkeypatch.setattr(contracts, "trading_calendar", candidate_calendar)
    package = types.ModuleType("_hk_candidate_parts")
    package.__path__ = [str(SOURCE / "infrastructure/scheduling/_executor_registry_parts")]
    monkeypatch.setitem(sys.modules, "_hk_candidate_parts", package)
    split = load("_hk_candidate_parts.preselection", SOURCE / "infrastructure/scheduling/_executor_registry_parts/preselection.py")
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    monkeypatch.setattr(registry, "_verified_preselection_source", lambda **kw: (None, "missing"), raising=False)
    monkeypatch.setattr(split, "_FixedExecutorRegistry__verified_preselection_source_body", lambda *a, **kw: (None, "missing"))
    monkeypatch.setattr(registry, "_decoded_stdout", lambda result: result["_authoritative_payload"], raising=False)
    result = split._FixedExecutorRegistry__preselection_pools_body(vars(runtime[0]), registry, request())
    assert argument(calls, "scripts.update_hk_0_2_panel", "--through-date") == "20261016"
    assert argument(calls, "scripts.materialize_hk_0_2", "--signal-date") == "20261016"
    assert result["hk_lane_status"] == "SUCCEEDED"
    sys.modules["contracts.trading_calendar"] = original_calendar


@pytest.mark.skipif(BASELINE, reason="overlay regression")
def test_real_retry_stops_at_hk_preparation_without_entering_a(runtime, tmp_path, monkeypatch):
    import infrastructure.isolated_package_loader as loader
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    class Store:
        def __init__(self, root): pass
        def _entry_key(self, date, role): return "missing-source"
        def _load_latest(self): return {"entries": {}}
    fake = SimpleNamespace(SafeRootStore=Store, HK_0_2_ROLE="hk-role")
    monkeypatch.setattr(loader, "load_isolated_package_module", lambda *a, **kw: fake)
    def fail_preparation(module, args, **kw):
        calls.append((module, args, kw))
        return {"status": "FAILED", **FLAGS}
    monkeypatch.setattr(registry, "_run", fail_preparation)
    result = runtime[1]._retry_missing_hk_only(registry, request(), signal_date="20261016",
        target_date="20261020", eligibility_source_date="20261016", a_identity={"sha": "retained-a"})
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["A_producer_called"] is False
    assert argument(calls, "scripts.update_hk_0_2_panel", "--through-date") == "20261016"
    assert len(calls) == 1
    assert not registry.data_root.exists()


@pytest.mark.skipif(BASELINE, reason="overlay regression")
@pytest.mark.parametrize("failed_module,first_gate", [("scripts.update_hk_0_2_panel", "HK_PRICE_PANEL"), ("ops.ensure_hk_security_master", "HK_SECURITY_MASTER")])
def test_normal_preparation_failure_keeps_scoring_gate_closed(runtime, tmp_path, monkeypatch, failed_module, first_gate):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    def run(module, args, **kwargs):
        calls.append((module, args, kwargs))
        failed = module == failed_module
        return {"status": "FAILED" if failed else "SUCCEEDED", "exit_code": int(failed),
            "stderr": "fixture prerequisite unavailable" if failed else "", "stdout": "",
            "_authoritative_payload": {"formal_pool_gate": {"required": {"hkconnect_d1_top100": {"ready": False}}}}, **FLAGS}
    monkeypatch.setattr(registry, "_run", run)
    result = registry._preselection_pools(request())
    assert "scripts.materialize_hk_0_2" not in [name for name, args, kwargs in calls]
    assert result["status"] == "FAILED" and result["first_gate"] == first_gate
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert argument(calls, "ops.materialize_shared_v192_preselection", "--signal-date") == "20261019"


def retained_shared_module():
    from infrastructure.isolated_package_loader import load_isolated_package_module
    module = load_isolated_package_module(SHARED, package_directory="shared_data",
        module_leaf="hk_0_2", namespace_prefix="hk_top100_actual_contract")
    assert Path(module.__file__).resolve() == (SHARED / "shared_data/hk_0_2.py").resolve()
    return module


def retained_reader_signature():
    signature = inspect.signature(retained_shared_module().read_verified_hk_0_2_pool)
    assert tuple(signature.parameters) == ("store_root", "target_date", "expected_signal_date")
    return signature


def retained_cli_parser():
    # Execute only the actual retained parser declarations, never its imports,
    # strict read, scoring, materialization, or provider logic.
    path = SHARED / "scripts/materialize_hk_0_2.py"
    main = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    declarations = []
    for node in main.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "args" for t in node.targets):
            break
        declarations.append(node)
    assert len(declarations) == 5
    scope = dict(argparse=argparse, Path=Path)
    exec(compile(ast.Module(body=declarations, type_ignores=[]), str(path), "exec"), scope)
    return scope["parser"]


@pytest.mark.skipif(BASELINE, reason="incremental actual-contract regression")
def test_actual_facade_real_retry_reaches_scorer_with_retained_cli(runtime, tmp_path, monkeypatch):
    import infrastructure.isolated_package_loader as loader
    module = retained_shared_module()
    signature = inspect.signature(module.read_verified_hk_0_2_pool)
    signature.bind(tmp_path, target_date="20261020", expected_signal_date="20261016")
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch,
        reuse={"hk_missing_retry": True, "a_identity": {"sha": "retained-a"}})
    class MissingStore:
        def __init__(self, root): pass
        def _entry_key(self, date, role): return "absent"
        def _load_latest(self): return {"entries": {}}
    monkeypatch.setattr(module, "SafeRootStore", MissingStore)
    monkeypatch.setattr(loader, "load_isolated_package_module", lambda *a, **kw: module)
    def run(name, args, **kwargs):
        calls.append((name, args, kwargs))
        if name == "scripts.materialize_hk_0_2":
            parsed = retained_cli_parser().parse_args(args)
            assert parsed.signal_date == "20261016" and parsed.target_date == "20261020"
            return {"status": "FAILED", **FLAGS}  # stop before real read/score/write
        return {"status": "SUCCEEDED", **FLAGS}
    monkeypatch.setattr(registry, "_run", run)
    result = registry._preselection_pools(request())
    assert [name for name, args, kw in calls] == ["scripts.update_hk_0_2_panel", "ops.ensure_hk_security_master", "scripts.materialize_hk_0_2"]
    assert argument(calls, "scripts.update_hk_0_2_panel", "--through-date") == "20261016"
    assert argument(calls, "ops.ensure_hk_security_master", "--trade-date") == "20261016"
    assert result["A_producer_called"] is False and result["failure_class"] == "UPSTREAM_NOT_READY"
    assert not registry.data_root.exists()


@pytest.mark.skipif(BASELINE, reason="incremental actual-contract regression")
def test_unsupported_split_normal_rejects_before_hk_prepare_and_keeps_a(runtime, tmp_path, monkeypatch):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    result = registry._preselection_pools(request("20261002", "20261008"))
    assert not any(name in {"scripts.update_hk_0_2_panel", "ops.ensure_hk_security_master", "scripts.materialize_hk_0_2"} for name, args, kw in calls)
    assert argument(calls, "ops.materialize_shared_v192_preselection", "--signal-date") == "20261002"
    assert result["hk_date_contract_error"] == "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
    assert result["status"] == "FAILED" and result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["first_gate"] == "HK_DATE_CONTRACT"


@pytest.mark.skipif(BASELINE, reason="incremental actual-contract regression")
def test_unsupported_split_real_retry_rejects_before_loader_or_prepare(runtime, tmp_path, monkeypatch):
    import infrastructure.isolated_package_loader as loader
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    monkeypatch.setattr(loader, "load_isolated_package_module", lambda *a, **kw: pytest.fail("unsupported split loaded shared module"))
    result = runtime[1]._retry_missing_hk_only(registry, request("20261002", "20261008"),
        signal_date="20261002", target_date="20261005", eligibility_source_date="20260930", a_identity={"sha": "retained-a"})
    assert result["reason"] == "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM" and result["write_performed"] is False
    assert calls == [] and not registry.data_root.exists()


@pytest.mark.skipif(BASELINE, reason="incremental actual-contract regression")
def test_unsupported_split_consumer_keeps_a_and_rejects_before_reader(runtime, tmp_path, monkeypatch):
    materializer = runtime[2]
    monkeypatch.setattr(materializer, "build_hourly_research_pool", lambda *a, **kw: {})
    monkeypatch.setattr(materializer, "load_baimao_preselection_pool", lambda *a, **kw: {})
    a_pool = {"pool_id": "a_d1_premarket_pool", "status": "V192_CANDIDATE_READY", "rows": [{"code": "000001"}]}
    artifacts = materializer.build_scheduled_artifacts(trade_date="20261008", signal_date="20261002", selector=None,
        input_root=tmp_path, data_root=tmp_path, shared_data_root=tmp_path, shared_package_root=tmp_path,
        hk_pool_reader=lambda *a, **kw: pytest.fail("unsupported split called reader"),
        reuse_formal_pools={"a_d1_premarket_pool": a_pool})
    hk = next(a for a in artifacts if a.get("pool_id") == "hkconnect_d1_top100")
    assert artifacts[0] == a_pool
    assert hk["status"] == "CANNOT_CONFIRM" and "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED" in hk["cannot_confirm"]


@pytest.mark.skipif(BASELINE, reason="second incremental dependency-branch regression")
@pytest.mark.parametrize("business,target,missing,expected_error", [
    ("20261002", "20261008", "hk_scorer", None),
    ("20261002", "20261008", "hk_security", None),
    ("20261019", "20261020", "hk_scorer", "fixed shared entry missing: materialize_hk_0_2.py"),
    ("20261002", "20261008", "a_selector", "fixed shared entry missing: materialize_v192_selector.py"),
])
def test_dependency_checks_follow_execution_branch(runtime, tmp_path, monkeypatch, business, target, missing, expected_error):
    registry, calls = registry_fixture(runtime, tmp_path, monkeypatch)
    absent = {
        "hk_scorer": registry.shared_package_root / "scripts/materialize_hk_0_2.py",
        "hk_security": registry.repo_root / "ops/ensure_hk_security_master.py",
        "a_selector": registry.shared_package_root / "scripts/materialize_v192_selector.py",
    }[missing]
    absent.unlink()  # only this test's temporary fixture file
    if expected_error:
        with pytest.raises(runtime[0].WorkloadExecutionError) as error:
            registry._preselection_pools(request(business, target))
        assert expected_error in error.value.result["stderr"]
        assert calls == []
    else:
        result = registry._preselection_pools(request(business, target))
        assert argument(calls, "ops.materialize_shared_v192_preselection", "--signal-date") == business
        assert result["hk_date_contract_error"] == "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
        assert result["hk_lane_status"] == "CANNOT_CONFIRM"
        assert not any(name in {"scripts.update_hk_0_2_panel", "ops.ensure_hk_security_master", "scripts.materialize_hk_0_2"} for name, args, kw in calls)
