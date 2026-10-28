from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
WRITER_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_NEXTDAY_POOL_20261015/writer"
)
CANDIDATE_APP = (
    WRITER_ROOT / "candidates" / "hk-nextday-pool-main-20261015-r1" / "app"
)
MISSING_HK_POOL = "EXACT_HK_POOL_LATEST_RUN_MISSING"
TRADE_DATE = "20261016"
SIGNAL_DATE = "20261015"
HK_0_2_ROLE = "HK_CONNECT_D1_TOP100_0_2"


class StoreError(Exception):
    """Small unit-test stand-in for the shared reader's typed store error."""


def _reader_module(reader):
    if hasattr(reader, "read_verified_hk_0_2_pool"):
        return reader
    return SimpleNamespace(
        read_verified_hk_0_2_pool=reader,
        StoreError=StoreError,
        HK_0_2_ROLE=HK_0_2_ROLE,
    )


def _canonical_scope(reader):
    return {
        "load_isolated_package_module": lambda *_args, **_kwargs: _reader_module(reader),
        "getattr": getattr,
        "dict": dict,
        "any": any,
        "Exception": Exception,
        "type": type,
        "isinstance": isinstance,
        "OSError": OSError,
        "ValueError": ValueError,
        "KeyError": KeyError,
        "TypeError": TypeError,
        "AttributeError": AttributeError,
        "str": str,
    }


def _canonical_verified_pool():
    rows = [
        {"code_norm": f"{rank:05d}", "rank": str(rank)}
        for rank in range(1, 101)
    ]
    return SimpleNamespace(
        rows=rows,
        run=SimpleNamespace(
            receipt={
                "status": "READY",
                "run_id": "synthetic-hk-run",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            verification={"artifact_sha256": "b" * 64, "row_count": 100},
        ),
    )


def _load_existing_registry_test_helpers():
    path = APP_ROOT / "tests" / "test_hk_only_preselection_execution_20261002.py"
    spec = importlib.util.spec_from_file_location(
        "hk_nextday_existing_registry_test_helpers", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_registry_result(fixture, *args, **kwargs):
    try:
        result, calls, *_rest = fixture._run_registry(*args, **kwargs)
        return result, calls
    except Exception as error:
        result = getattr(error, "result", None)
        if not isinstance(result, dict):
            raise
        return result, []


def _patch_canonical_exact_sources(
    monkeypatch: pytest.MonkeyPatch,
    hk_reader,
) -> dict[str, str]:
    registry_module = importlib.import_module(
        "infrastructure.scheduling.executor_registry"
    )
    preselection = importlib.import_module(
        "infrastructure.scheduling._executor_registry_parts.preselection"
    )
    original_loader = registry_module.load_isolated_package_module
    observed: dict[str, str] = {}

    def load_source(*args, **kwargs):
        if kwargs.get("module_leaf") == "hk_0_2":
            reader_module = _reader_module(hk_reader)
            if hasattr(hk_reader, "read_verified_hk_0_2_pool"):
                def observed_real_reader(root, **reader_kwargs):
                    observed.update(reader_kwargs)
                    return reader_module.read_verified_hk_0_2_pool(
                        root, **reader_kwargs
                    )

                return SimpleNamespace(
                    read_verified_hk_0_2_pool=observed_real_reader,
                    StoreError=reader_module.StoreError,
                    HK_0_2_ROLE=reader_module.HK_0_2_ROLE,
                )
            return reader_module
        return original_loader(*args, **kwargs)

    def ready_a_source(
        _self,
        *,
        module_leaf,
        reader_name,
        target_date,
        signal_date,
    ):
        assert module_leaf == "v192_selector"
        assert reader_name == "read_verified_v192_pool"
        observed["a_target_date"] = target_date
        observed["a_signal_date"] = signal_date
        return {
            "status": "READY",
            "run_id": "synthetic-a-run",
            "artifact_sha256": "a" * 64,
            "row_count": 1,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ""

    monkeypatch.setattr(registry_module, "load_isolated_package_module", load_source)
    monkeypatch.setattr(
        registry_module.FixedExecutorRegistry,
        "_verified_preselection_source",
        ready_a_source,
    )
    # The canonical body resolves this helper through executor_registry globals.
    assert hasattr(preselection, "_FixedExecutorRegistry__verified_preselection_source_body")
    return observed


def test_canonical_reader_classifies_only_exact_missing_latest_run() -> None:
    module = importlib.import_module(
        "infrastructure.scheduling._executor_registry_parts.preselection"
    )
    calls: list[dict] = []

    def missing_reader(_root, **kwargs):
        calls.append(kwargs)
        raise StoreError(
            f"no latest run for {TRADE_DATE} / {HK_0_2_ROLE}"
        )

    source, error = module._FixedExecutorRegistry__verified_preselection_source_body(
        _canonical_scope(missing_reader),
        SimpleNamespace(shared_data_root=Path("/synthetic/shared"), shared_package_root=Path("/synthetic/package")),
        module_leaf="hk_0_2",
        reader_name="read_verified_hk_0_2_pool",
        target_date=TRADE_DATE,
        signal_date=SIGNAL_DATE,
        eligibility_source_date=SIGNAL_DATE,
    )

    assert source is None
    assert error == MISSING_HK_POOL
    assert calls == [
        {
            "target_date": TRADE_DATE,
            "expected_signal_date": SIGNAL_DATE,
        }
    ]

    rejected_errors = (
        FileNotFoundError("hkconnect_d1_top100"),
        StoreError(f"no latest run for 20261015 / {HK_0_2_ROLE}"),
        StoreError("verified read failed closed: missing artifact.csv"),
        ValueError("HK_HISTORY_RESOLUTION_CACHE_PROOF_STALE"),
    )
    for rejected_error in rejected_errors:
        source, error = module._FixedExecutorRegistry__verified_preselection_source_body(
            _canonical_scope(
                lambda *_args, _error=rejected_error, **_kwargs: (
                    _ for _ in ()
                ).throw(_error)
            ),
            SimpleNamespace(
                shared_data_root=Path("/synthetic/shared"),
                shared_package_root=Path("/synthetic/package"),
            ),
            module_leaf="hk_0_2",
            reader_name="read_verified_hk_0_2_pool",
            target_date=TRADE_DATE,
            signal_date=SIGNAL_DATE,
            eligibility_source_date=SIGNAL_DATE,
        )
        assert source is None
        assert error == str(rejected_error)


def _real_shared_hk_reader(monkeypatch: pytest.MonkeyPatch):
    package_root = Path(
        os.environ.get(
            "V4_HK_TEST_SHARED_PACKAGE_ROOT",
            APP_ROOT / "upstreams" / "v3_shared_data",
        )
    )
    loader = importlib.import_module(
        "infrastructure.isolated_package_loader"
    ).load_isolated_package_module
    reader_module = loader(
        package_root,
        package_directory="shared_data",
        module_leaf="hk_0_2",
        namespace_prefix="hk_nextday_real_store_probe",
    )
    # Keep this test focused on the real HK latest/run reader and store. The
    # only stub is the separate security-master lookup that precedes it.
    monkeypatch.setattr(
        reader_module,
        "_load_verified_security_master",
        lambda _root, trade_date: (
            set(),
            {"trade_date": trade_date, "run_id": "isolated-security-master", "captured_at": "2026-10-15T17:30:00+08:00"},
        ),
    )
    return reader_module


def _canonical_read_real_store(reader_module, store_root: Path):
    preselection = importlib.import_module(
        "infrastructure.scheduling._executor_registry_parts.preselection"
    )
    return preselection._FixedExecutorRegistry__verified_preselection_source_body(
        _canonical_scope(reader_module),
        SimpleNamespace(
            shared_data_root=store_root,
            shared_package_root=Path("/synthetic/package"),
        ),
        module_leaf="hk_0_2",
        reader_name="read_verified_hk_0_2_pool",
        target_date=TRADE_DATE,
        signal_date=SIGNAL_DATE,
        eligibility_source_date=SIGNAL_DATE,
    )


def test_canonical_real_reader_empty_store_reaches_existing_producer_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader_module = _real_shared_hk_reader(monkeypatch)
    store_root = tmp_path / "empty-shared-store"
    store_root.mkdir()
    assert not (store_root / "latest.json").exists()

    source, error = _canonical_read_real_store(reader_module, store_root)

    assert source is None
    assert error == MISSING_HK_POOL


def test_canonical_real_reader_existing_run_without_artifact_stays_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader_module = _real_shared_hk_reader(monkeypatch)
    store_root = tmp_path / "existing-run-store"
    role = reader_module.HK_0_2_ROLE
    run_id = "existing-run-with-missing-artifact"
    store_module = importlib.import_module(reader_module.StoreError.__module__)
    latest = {
        "schema_version": store_module.LATEST_SCHEMA_VERSION,
        "entries": {
            f"{TRADE_DATE}/{role}": {
                "run_id": run_id,
                "owner": "v3_shared_data",
            }
        },
    }
    store_root.mkdir()
    (store_root / "latest.json").write_text(
        json.dumps(latest), encoding="utf-8"
    )
    (store_root / "runs" / TRADE_DATE / role / run_id).mkdir(parents=True)

    source, error = _canonical_read_real_store(reader_module, store_root)

    assert source is None
    assert error.startswith("run trio incomplete:")
    assert error.endswith("artifact.csv")
    assert error != MISSING_HK_POOL


@pytest.mark.parametrize("existing_local", [False, True])
def test_canonical_missing_hk_source_routes_only_to_HK_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_local: bool
) -> None:
    reader_module = _real_shared_hk_reader(monkeypatch)
    observed = _patch_canonical_exact_sources(monkeypatch, reader_module)
    if existing_local:
        stale = tmp_path / "data/preselection_pools" / TRADE_DATE / "hkconnect_d1_top100.json"
        stale.parent.mkdir(parents=True); stale.write_text('{"stale":true}')
    preselection = importlib.import_module("infrastructure.scheduling._executor_registry_parts.preselection")
    routed = []
    def only_HK(self, request, **kwargs):
        routed.append(kwargs)
        return {"status": "SUCCEEDED", "A_producer_called": False,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    monkeypatch.setattr(preselection, "_retry_missing_hk_only", only_HK)
    fixture = _load_existing_registry_test_helpers()
    result, calls = _run_registry_result(fixture, tmp_path, monkeypatch, SIGNAL_DATE,
        a_input_ready=True, hk_input_ready=True, selector_ready=True)
    assert result["status"] == "SUCCEEDED" and result["A_producer_called"] is False
    assert calls == [] and len(routed) == 1
    assert routed[0]["signal_date"] == SIGNAL_DATE and routed[0]["target_date"] == TRADE_DATE
    assert routed[0]["a_identity"]["status"] == "READY"


def _seed_existing_run_without_artifact(reader_module, store_root: Path) -> None:
    role = reader_module.HK_0_2_ROLE
    run_id = "existing-run-with-missing-artifact"
    store_module = importlib.import_module(reader_module.StoreError.__module__)
    latest = {
        "schema_version": store_module.LATEST_SCHEMA_VERSION,
        "entries": {
            f"{TRADE_DATE}/{role}": {
                "run_id": run_id,
                "owner": "v3_shared_data",
            }
        },
    }
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / "latest.json").write_text(
        json.dumps(latest), encoding="utf-8"
    )
    (store_root / "runs" / TRADE_DATE / role / run_id).mkdir(parents=True)


def test_canonical_existing_hk_run_without_artifact_stays_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader_module = _real_shared_hk_reader(monkeypatch)
    _seed_existing_run_without_artifact(reader_module, tmp_path / "shared-data")
    _patch_canonical_exact_sources(monkeypatch, reader_module)
    fixture = _load_existing_registry_test_helpers()

    result, calls = _run_registry_result(
        fixture,
        tmp_path,
        monkeypatch,
        SIGNAL_DATE,
        a_input_ready=True,
        hk_input_ready=True,
        selector_ready=True,
    )

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "HK_HISTORY_RESOLUTION_CACHE_REJECTED"
    assert result["hk_lane_status"] == "QUARANTINED"
    assert result["producer_called"] is False
    assert calls == []
    assert all(
        result.get(flag) is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )


def test_canonical_invalid_hk_source_stays_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_canonical_exact_sources(
        monkeypatch,
        lambda _root, **_kwargs: (_ for _ in ()).throw(
            ValueError("HK_HISTORY_RESOLUTION_CACHE_PROOF_STALE")
        ),
    )
    fixture = _load_existing_registry_test_helpers()
    result, calls = _run_registry_result(
        fixture,
        tmp_path,
        monkeypatch,
        SIGNAL_DATE,
        a_input_ready=True,
        hk_input_ready=True,
        selector_ready=True,
    )

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "HK_HISTORY_RESOLUTION_CACHE_REJECTED"
    assert result["hk_lane_status"] == "QUARANTINED"
    assert result["producer_called"] is False
    assert calls == []
    assert all(
        result.get(flag) is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )


def _runtime_pool(pool_id: str) -> dict:
    market = "A" if pool_id == "a_d1_premarket_pool" else "HK"
    count = 1 if market == "A" else 100
    rows = [
        {
            "code": f"{rank:05d}",
            "rank": rank,
            **({"market": "HK"} if market == "HK" else {}),
        }
        for rank in range(1, count + 1)
    ]
    return {
        "pool_id": pool_id,
        "market": market,
        "trade_date": TRADE_DATE,
        "target_date": TRADE_DATE,
        "signal_date": SIGNAL_DATE,
        "source_role": (
            "SHARED_VERIFIED_V192"
            if market == "A"
            else "SHARED_VERIFIED_HK_0_2"
        ),
        "source_merge_role": "MAIN_STAGE_INPUT",
        "stage_selection_eligible": True,
        "status": "READY",
        "source_sha256": "a" * 64,
        "source_artifact_sha256": "b" * 64,
        "source_manifest_sha256": "c" * 64,
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _load_runtime_candidate(monkeypatch: pytest.MonkeyPatch):
    path = CANDIDATE_APP / "infrastructure" / "scheduling" / "executor_registry_preselection.py"
    assert path.is_file(), f"candidate runtime is missing: {path}"
    monkeypatch.syspath_prepend(str(CANDIDATE_APP))
    spec = importlib.util.spec_from_file_location(
        "hk_nextday_runtime_candidate_preselection", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.WorkloadExecutionError = RuntimeError
    module._default_runner = object()
    module._V192_PRESELECTION_TIMEOUT_SECONDS = 1800
    return module


def _runtime_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
):
    module = _load_runtime_candidate(monkeypatch)
    a_pool = _runtime_pool("a_d1_premarket_pool")
    hk_pool = _runtime_pool("hkconnect_d1_top100")
    store_calls: list[tuple[str, str]] = []
    reader_calls: list[dict] = []
    producer_calls: list[tuple[str, list[str]]] = []

    class FakeStore:
        def __init__(self, _root):
            pass

        def read_pool(self, trade_date: str, pool_id: str):
            store_calls.append((trade_date, pool_id))
            if pool_id == "a_d1_premarket_pool":
                return a_pool
            if mode == "missing" and pool_id == "hkconnect_d1_top100":
                raise FileNotFoundError(pool_id)
            return hk_pool

    def verified_reader(_root, *, target_date: str, expected_signal_date: str):
        reader_calls.append(
            {"target_date": target_date, "expected_signal_date": expected_signal_date}
        )
        if mode == "invalid":
            raise ValueError("HK_HISTORY_RESOLUTION_CACHE_PROOF_STALE")
        if mode == "sha_mismatch":
            artifact_sha = "f" * 64
        else:
            artifact_sha = hk_pool["source_artifact_sha256"]
        rows = [
            {"code_norm": row["code"], "rank": row["rank"]}
            for row in hk_pool["rows"]
        ]
        return SimpleNamespace(
            rows=rows,
            run=SimpleNamespace(
                verification={
                    "artifact_sha256": artifact_sha,
                    "manifest_sha256": hk_pool["source_manifest_sha256"],
                }
            ),
        )

    monkeypatch.setattr(module, "PreselectionPoolStore", FakeStore)
    loader = importlib.import_module("infrastructure.isolated_package_loader")
    monkeypatch.setattr(
        loader,
        "load_isolated_package_module",
        lambda *_args, **_kwargs: SimpleNamespace(
            read_verified_hk_0_2_pool=verified_reader
        ),
    )

    package = tmp_path / "shared-package"
    scripts = package / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# isolated fixture\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    (repo_root / "ops").mkdir(parents=True)
    (repo_root / "ops" / "ensure_hk_security_master.py").write_text(
        "# isolated fixture\n", encoding="utf-8"
    )
    selector_root = tmp_path / "selector"
    selector_root.mkdir()
    selector = selector_root / "selector.parquet"
    selector.write_bytes(b"synthetic-selector")
    monkeypatch.setattr(module, "resolve_selector_panel", lambda *_args: selector)

    class FakeRegistry:
        def __init__(self):
            self.data_root = tmp_path / "data"
            self.shared_data_root = tmp_path / "shared"
            self.hk_universe_root = tmp_path / "hk-universe"
            self.shared_package_root = package
            self.shared_futu_python_executable = tmp_path / "futu-python"
            self.selector_data_root = selector_root
            self.preselection_input_root = tmp_path / "preselection-input"
            self.stage_selection_root = None
            self.repo_root = repo_root
            self.hk_0_2_python_executable = tmp_path / "hk-python"
            self.hk_0_2_tdx_root = tmp_path / "hk-tdx"
            self._runner = object()
            for root in (
                self.data_root,
                self.shared_data_root,
                self.hk_universe_root,
                self.preselection_input_root,
            ):
                root.mkdir(parents=True, exist_ok=True)

        def _verified_formal_pool_reuse(self, trade_date: str):
            return module._verified_formal_pool_reuse(self, trade_date)

        def _hk_0_2_runtime_error(self):
            return None

        def _failure_result(self, workload_id, modules, message):
            return {
                "status": "FAILED",
                "workload_id": workload_id,
                "modules": modules,
                "exit_code": 1,
                "stderr": message,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

        def _run(self, module_name: str, arguments: list[str], **_kwargs):
            producer_calls.append((module_name, list(arguments)))
            result = {
                "status": "SUCCEEDED",
                "exit_code": 0,
                "stdout": "{}",
                "stderr": "",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            if module_name == "ops.materialize_scheduled_preselection":
                result["_authoritative_payload"] = {
                    "formal_pool_gate": {
                        "required": {
                            "hkconnect_d1_top100": {"ready": True, "status": "READY"}
                        }
                    }
                }
            return result

    registry = FakeRegistry()
    request = SimpleNamespace(business_date=SIGNAL_DATE, target_date=TRADE_DATE)
    result = module._preselection_pools(registry, request)
    return result, producer_calls, store_calls, reader_calls


def test_runtime_missing_exact_hk_artifact_reaches_existing_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, producers, store_calls, reader_calls = _runtime_run(
        tmp_path, monkeypatch, "missing"
    )

    modules = [module for module, _args in producers]
    assert "scripts.update_hk_0_2_panel" in modules
    assert "ops.ensure_hk_security_master" in modules
    assert "scripts.materialize_hk_0_2" in modules
    hk_args = next(
        args for module, args in producers if module == "scripts.materialize_hk_0_2"
    )
    assert hk_args[hk_args.index("--target-date") + 1] == TRADE_DATE
    assert hk_args[hk_args.index("--signal-date") + 1] == SIGNAL_DATE
    assert store_calls == [
        (TRADE_DATE, "a_d1_premarket_pool"),
        (TRADE_DATE, "hkconnect_d1_top100"),
    ]
    assert reader_calls == []
    assert result["status"] == "SUCCEEDED"
    assert all(
        result.get(flag) is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )


@pytest.mark.parametrize("mode", ["invalid", "sha_mismatch"])
def test_runtime_invalid_or_unbound_hk_cache_stays_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    result, producers, store_calls, reader_calls = _runtime_run(
        tmp_path, monkeypatch, mode
    )

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "HK_HISTORY_RESOLUTION_CACHE_REJECTED"
    assert result["hk_lane_status"] == "QUARANTINED"
    assert result["hk_quality_rejected"] is True
    assert producers == []
    assert store_calls == [
        (TRADE_DATE, "a_d1_premarket_pool"),
        (TRADE_DATE, "hkconnect_d1_top100"),
    ]
    assert len(reader_calls) == 1
    assert all(
        result.get(flag) is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )


def test_runtime_valid_a_hk_cache_pair_keeps_exact_reuse_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, producers, store_calls, reader_calls = _runtime_run(
        tmp_path, monkeypatch, "valid"
    )

    modules = [module for module, _args in producers]
    assert result["status"] == "SUCCEEDED"
    assert result["formal_pool_reuse"]["a_pool_id"] == "a_d1_premarket_pool"
    assert result["formal_pool_reuse"]["hk_pool_id"] == "hkconnect_d1_top100"
    assert result["formal_pool_reuse"]["hk_source_sha256"] == "a" * 64
    assert "scripts.materialize_hk_0_2" not in modules
    assert "ops.materialize_shared_v192_preselection" not in modules
    materializer_args = next(
        args
        for module, args in producers
        if module == "ops.materialize_scheduled_preselection"
    )
    assert "--reuse-formal-pools" in materializer_args
    assert store_calls == [
        (TRADE_DATE, "a_d1_premarket_pool"),
        (TRADE_DATE, "hkconnect_d1_top100"),
    ]
    assert reader_calls == [
        {"target_date": TRADE_DATE, "expected_signal_date": SIGNAL_DATE}
    ]

# Coordinated repair: exercise the actual deployed mapper/store/gate, not a
# replacement local-cache contract. No model or production source is written.
COMBINED_H = APP_ROOT / 'docs/handoffs/hk_tdx_conflict_repair_20261015'
COMBINED_BASE = Path(os.environ.get('V4_HK_COMBINED_MAIN_APP', Path.home() / 'Library/Application Support/com.lexi.v4.local/releases/hk-nextday-pool-main-20261015-r1/app'))


def _combined_fixture(tmp_path, monkeypatch, mode='shared_ready'):
    import hashlib
    monkeypatch.syspath_prepend(str(COMBINED_BASE))
    source = Path(os.environ.get('V4_HK_COMBINED_MAIN_SOURCE', COMBINED_H / 'source_projection/main/infrastructure/scheduling/executor_registry_preselection.py'))
    spec = importlib.util.spec_from_file_location('_combined_main_projection', source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    store = module.PreselectionPoolStore(tmp_path / 'data')
    # Real physical A artifact, receipt and manifest; no values leave this fixture.
    a = _runtime_pool('a_d1_premarket_pool')
    a.update(schema_version='v3_5.preselection_pool.v1', display_name='Fixture A',
        producer_id='fixture', source_path='fixture', cannot_confirm=[])
    store.materialize(a)
    day = tmp_path / 'data/preselection_pools' / TRADE_DATE
    protected = {str(p.relative_to(day)): p.read_bytes() for p in day.rglob('*') if p.is_file()}
    rows = [{
        'code_norm': f'{i:05d}', 'rank': str(i), 'score_prob_active': str(1 - i / 1000),
        'signal_date': SIGNAL_DATE, 'target_date': TRADE_DATE, 'name': 'Fixture',
        'd1_freshness_status': 'PASS', 'selected_strategy': 'prob_active',
        'history_resolution_identity': 'e' * 64,
        'production_allowed': 'false', 'buy_gate_updated': 'false', 'orders_sent': 'false'
    } for i in range(1, 101)]
    pool = SimpleNamespace(rows=rows, run=SimpleNamespace(
        receipt={'status': 'READY', 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False},
        verification={'status': 'READY', 'row_count': 100, 'run_id': 'synthetic-hk-run',
            'artifact_relative': f'runs/{TRADE_DATE}/HK_CONNECT_D1_TOP100_0_2/synthetic-hk-run/artifact.csv',
            'artifact_sha256': 'b' * 64, 'manifest_sha256': 'c' * 64, 'receipt_sha256': 'd' * 64},
        manifest={}))
    state = {'ready': mode not in {'shared_missing', 'upstream_failure'}, 'calls': []}
    def strict_reader(_root, *, target_date, expected_signal_date):
        assert (target_date, expected_signal_date) == (TRADE_DATE, SIGNAL_DATE)
        if mode == 'existing_bad': raise StoreError('artifact SHA mismatch')
        if not state['ready']: raise StoreError(f'no latest run for {target_date} / {HK_0_2_ROLE}')
        return pool
    class SourceStore:
        def __init__(self, root): pass
        def _entry_key(self, target, role): return target + '/' + role
        def _load_latest(self):
            return {'entries': {TRADE_DATE+'/'+HK_0_2_ROLE: {'run_id':'synthetic-hk-run'}} if state['ready'] else {}}
    shared_module = SimpleNamespace(StoreError=StoreError, HK_0_2_ROLE=HK_0_2_ROLE,
        SafeRootStore=SourceStore,read_verified_hk_0_2_pool=strict_reader)
    loader = importlib.import_module('infrastructure.isolated_package_loader')
    monkeypatch.setattr(loader, 'load_isolated_package_module', lambda *a, **k: shared_module)
    # Load exactly the candidate main mapper; default imports can otherwise
    # resolve a different canonical version in a larger pytest process.
    spec = importlib.util.spec_from_file_location('_combined_actual_mapper', COMBINED_BASE / 'domains/preselection_materializer.py')
    mapper = importlib.util.module_from_spec(spec); spec.loader.exec_module(mapper)
    materializer = importlib.import_module('domains.preselection_materializer')
    monkeypatch.setattr(materializer, 'build_shared_hk_0_2_pool', mapper.build_shared_hk_0_2_pool)
    # Assert actual mapper has its historical status/date contract.
    mapped = mapper.build_shared_hk_0_2_pool(tmp_path / 'shared', trade_date=TRADE_DATE,
        signal_date=SIGNAL_DATE, reader=lambda *a, **k: pool)
    assert mapped['status'] == 'STRICT_0_2_READY' and mapped['signal_date'] == SIGNAL_DATE
    class Registry:
        data_root = tmp_path / 'data'
        shared_data_root = tmp_path / 'shared'
        shared_package_root = tmp_path / 'package'
        hk_universe_root = tmp_path / 'universe'
        repo_root = COMBINED_BASE
        hk_0_2_python_executable = Path(sys.executable)
        shared_futu_python_executable = Path(sys.executable)
        hk_0_2_tdx_root = tmp_path / 'tdx'
        _verified_formal_pool_reuse = module._verified_formal_pool_reuse
        _preselection_pools = module._preselection_pools
        def _hk_0_2_runtime_error(self): return None
        def _run(self, name, arguments, **kwargs):
            assert name in {'scripts.update_hk_0_2_panel', 'ops.ensure_hk_security_master', 'scripts.materialize_hk_0_2'}, ('FORBIDDEN_A_OR_AGGREGATE_CALL', name)
            state['calls'].append(name)
            if mode == 'upstream_failure': return {'status': 'FAILED'}
            if name == 'scripts.materialize_hk_0_2': state['ready'] = True
            return {'status': 'SUCCEEDED'}
    registry = Registry()
    def unchanged():
        for relative, raw in protected.items():
            current = (day / relative).read_bytes()
            if relative == 'manifest.json':
                original = json.loads(raw); after = json.loads(current)
                assert {k:v for k,v in after.items() if k != 'hkconnect_d1_top100'} == original
            else: assert current == raw
    return module, registry, store, state, pool, unchanged


@pytest.mark.parametrize('mode,expected_calls', [('shared_ready', []), ('shared_missing', [
    'scripts.update_hk_0_2_panel', 'ops.ensure_hk_security_master', 'scripts.materialize_hk_0_2'])])
def test_combined_actual_mapper_store_exact_gate_preserves_A(tmp_path, monkeypatch, mode, expected_calls):
    module, registry, store, state, pool, unchanged = _combined_fixture(tmp_path, monkeypatch, mode)
    result = registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE, target_date=TRADE_DATE))
    assert result['status'] == 'SUCCEEDED' and result['hk_lane_status'] == 'READY'
    assert state['calls'] == expected_calls and result['A_producer_called'] is False
    local = store.read_pool(TRADE_DATE, 'hkconnect_d1_top100')
    assert local['status'] == 'READY' and local['signal_date'] == SIGNAL_DATE
    assert local['source_manifest_sha256'] == pool.run.verification['manifest_sha256']
    assert [(r['code_norm'],str(r['rank'])) for r in local['rows']] == [(r['code_norm'],str(r['rank'])) for r in pool.rows]
    assert registry._verified_formal_pool_reuse(TRADE_DATE)['status'] == 'SUCCEEDED'
    unchanged()


@pytest.mark.parametrize('mode', ['existing_bad', 'upstream_failure', 'partial_receipt', 'manifest_entry', 'pending_journal', 'race', 'wrong_rank', 'wrong_date'])
def test_combined_missing_retry_rejects_bad_or_racing_inputs_without_A(tmp_path, monkeypatch, mode):
    source_mode = 'shared_missing' if mode in {'upstream_failure', 'race'} else 'shared_ready'
    if mode in {'existing_bad', 'upstream_failure'}: source_mode = mode
    module, registry, store, state, pool, unchanged = _combined_fixture(tmp_path, monkeypatch, source_mode)
    day = registry.data_root / 'preselection_pools' / TRADE_DATE
    if mode == 'partial_receipt':
        p = day / 'receipts/hkconnect_d1_top100.json'; p.write_text('{}')
    elif mode == 'manifest_entry':
        p = day / 'manifest.json'; v=json.loads(p.read_bytes());v['hkconnect_d1_top100']='e'*64;p.write_text(json.dumps(v))
    elif mode == 'pending_journal':
        p=registry.data_root/'preselection_pending_commits'/TRADE_DATE/'foreign.json';p.parent.mkdir(parents=True);p.write_text('{}')
    elif mode == 'wrong_rank': pool.rows[-1]['rank']='99'
    elif mode == 'wrong_date': pool.rows[-1]['signal_date']='20261014'
    elif mode == 'race':
        original=registry._run
        def run(name, *args, **kwargs):
            result=original(name,*args,**kwargs)
            if name=='scripts.update_hk_0_2_panel':
                p=day/'hkconnect_d1_top100.json';p.write_text('{"foreign":true}')
            return result
        registry._run=run
    result=registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE,target_date=TRADE_DATE))
    assert result['status']=='FAILED' and result['A_producer_called'] is False
    if mode == 'upstream_failure': assert result['failure_class'] == 'UPSTREAM_NOT_READY'
    assert all(name.startswith('scripts.update_hk') or name in {'ops.ensure_hk_security_master','scripts.materialize_hk_0_2'} for name in state['calls'])
    if mode not in {'manifest_entry'}:unchanged()
    if mode not in {'race'}:assert not (day/'hkconnect_d1_top100.json').exists()


def test_combined_actual_strict_source_rejects_old_proof_without_any_producer(tmp_path, monkeypatch):
    """Real owned old run + final actual strict reader, no scoring or writes."""
    monkeypatch.syspath_prepend(str(COMBINED_BASE))
    loader = importlib.import_module('infrastructure.isolated_package_loader')
    actual_loader = _combined_actual_loader().load_isolated_package_module
    module, registry, store, state, pool, unchanged = _combined_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(loader, 'load_isolated_package_module', actual_loader)
    registry.shared_package_root = Path(os.environ.get('V4_HK_COMBINED_SHARED_ROOT',COMBINED_H/'isolated_loader_projection_package'))
    registry.shared_data_root = Path.home() / 'Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'
    monkeypatch.setenv('V4_HK_HISTORY_RESOLUTION_POINTER', str(COMBINED_H / 'history_resolution_latest.combined.prepared.json'))
    # Existing target15 run predates the new resolution. A correct consumer must
    # reject it, rather than treating its failure as a permission to re-produce.
    result = module._retry_missing_hk_only(registry, SimpleNamespace(),
        signal_date='20261014', target_date='20261015', a_identity={'artifact_sha256':'a'*64})
    assert result['status']=='FAILED' and result['A_producer_called'] is False
    assert not state['calls'] and ('provenance mismatch: history_value_view' in result['reason'] or 'PROOF_STALE' in result['reason'] or 'PROOF_BINDING_MISMATCH' in result['reason'])
    assert 'dynamic import' not in result['reason']
    unchanged()


def test_combined_helper_identical_in_canonical_and_actual_projection():
    import ast
    canonical=APP_ROOT/'infrastructure/scheduling/_executor_registry_parts/preselection.py'
    actual=COMBINED_H/'source_projection/main/infrastructure/scheduling/executor_registry_preselection.py'
    functions=[]
    for p in [canonical,actual]:
        tree=ast.parse(p.read_text());functions.append(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_retry_missing_hk_only'))
    assert ast.dump(functions[0])==ast.dump(functions[1])


@pytest.mark.parametrize('race_kind', ['same_payload', 'foreign_payload', 'partial_receipt'])
def test_combined_import_lock_rechecks_create_absent_even_identical_race(tmp_path, monkeypatch, race_kind):
    from contextlib import contextmanager
    module, registry, store, state, pool, unchanged = _combined_fixture(tmp_path, monkeypatch)
    locks=importlib.import_module('infrastructure.interprocess_lock');actual_lock=locks.owned_interprocess_lock
    mapper=importlib.import_module('domains.preselection_materializer');actual_mapper=mapper.build_shared_hk_0_2_pool
    captured={}
    def capture(*args, **kwargs):
        payload=actual_mapper(*args,**kwargs);captured['payload']=payload;return payload
    monkeypatch.setattr(mapper,'build_shared_hk_0_2_pool',capture)
    @contextmanager
    def race(path, **kwargs):
        if kwargs.get('timeout_message')=='HK-only retry import lock timeout':
            payload=dict(captured['payload'])
            if race_kind=='partial_receipt':
                (registry.data_root/'preselection_pools'/TRADE_DATE/'receipts/hkconnect_d1_top100.json').write_text('{"foreign":true}')
            else:
                if race_kind=='foreign_payload':payload['source_run_id']='foreign-run'
                store.materialize(payload)
            captured['racing_bytes']=(registry.data_root/'preselection_pools'/TRADE_DATE/'hkconnect_d1_top100.json').read_bytes() if race_kind!='partial_receipt' else None
        with actual_lock(path,**kwargs) as lease:yield lease
    monkeypatch.setattr(locks,'owned_interprocess_lock',race)
    result=registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE,target_date=TRADE_DATE))
    assert result['status']=='FAILED' and result['reason']=='HK_RETRY_LOCAL_PARTIAL_OR_RACE'
    assert not state['calls'] and result['A_producer_called'] is False
    if captured['racing_bytes'] is not None:
        assert (registry.data_root/'preselection_pools'/TRADE_DATE/'hkconnect_d1_top100.json').read_bytes()==captured['racing_bytes']
    unchanged()


def test_combined_pending_A_journal_is_not_recovered_or_rewritten(tmp_path, monkeypatch):
    module, registry, store, state, pool, unchanged=_combined_fixture(tmp_path,monkeypatch)
    pending=registry.data_root/'preselection_pending_commits'/TRADE_DATE/'a_d1_premarket_pool.json'
    pending.parent.mkdir(parents=True);pending.write_bytes(b'{"preserve":"A pending"}')
    before=pending.read_bytes()
    def forbidden_read(_date):raise AssertionError('A pool reader must not recover pending journal')
    registry._verified_formal_pool_reuse=forbidden_read
    result=registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE,target_date=TRADE_DATE))
    assert result['reason']=='HK_RETRY_PENDING_JOURNAL' and result['write_performed'] is False
    assert pending.read_bytes()==before and not state['calls'];unchanged()


def test_combined_real_resolution_admission_and_actual_local_gate(tmp_path, monkeypatch):
    module, registry, store, state, pool, unchanged=_combined_fixture(tmp_path,monkeypatch)
    loader=importlib.import_module('infrastructure.isolated_package_loader')
    # Import the immutable final resolver under a unique standalone identity;
    # no model is loaded or scored. The strict-reader adapter below adds its
    # actual admission validation to the existing mapper/store/gate test.
    shared=Path.home()/'Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r3/app/upstreams/v3_shared_data'
    spec=importlib.util.spec_from_file_location('_combined_actual_resolution',Path(os.environ.get('V4_HK_COMBINED_SHARED_ROOT',COMBINED_H/'isolated_loader_projection_package'))/'shared_data/hk_history_resolution.py')
    resolver=importlib.util.module_from_spec(spec);spec.loader.exec_module(resolver)
    owner=Path.home()/'Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2'
    policy=resolver.ResolutionPolicy(owner,pointer_path=COMBINED_H/'history_resolution_latest.combined.prepared.json')
    proof=policy._trusted_score_proof(SIGNAL_DATE);token=policy.encode_proof(proof)
    for row, code in zip(pool.rows,proof['score_coverage']['scoreable_signal_codes'][:100]):row['code_norm']=code
    def reader(root, *,target_date,expected_signal_date):
        assert (target_date,expected_signal_date)==(TRADE_DATE,SIGNAL_DATE)
        policy.verify_proof(token,end=expected_signal_date,consumer='HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1',codes=[r['code_norm'] for r in pool.rows])
        return pool
    monkeypatch.setattr(loader,'load_isolated_package_module',lambda *a,**kw:SimpleNamespace(
        StoreError=StoreError,HK_0_2_ROLE=HK_0_2_ROLE,SafeRootStore=type('SourceStore',(),{'__init__':lambda self,root:None,'_entry_key':lambda self,t,r:t+'/'+r,'_load_latest':lambda self:{'entries':{TRADE_DATE+'/'+HK_0_2_ROLE:{}}}}),read_verified_hk_0_2_pool=reader))
    result=registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE,target_date=TRADE_DATE))
    assert result['status']=='SUCCEEDED' and not state['calls'];unchanged()
    assert registry._verified_formal_pool_reuse(TRADE_DATE)['status']=='SUCCEEDED'
    # A formerly held real code cannot be substituted into this source projection.
    pool.rows[0]['code_norm']='HK.00165'
    rejected=registry._verified_formal_pool_reuse(TRADE_DATE)
    assert rejected['hk_lane_status']=='QUARANTINED' and rejected['producer_called'] is False
    unchanged()


def test_combined_canonical_helper_without_legacy_formal_gate(tmp_path,monkeypatch):
    module, registry, store, state, pool, unchanged=_combined_fixture(tmp_path,monkeypatch)
    attributes={name:getattr(registry,name) for name in ['data_root','shared_data_root','shared_package_root',
        'hk_universe_root','repo_root','hk_0_2_python_executable','shared_futu_python_executable','hk_0_2_tdx_root','_hk_0_2_runtime_error','_run']}
    result=module._retry_missing_hk_only(SimpleNamespace(**attributes),SimpleNamespace(),
        signal_date=SIGNAL_DATE,target_date=TRADE_DATE,a_identity={'status':'READY'})
    assert result['status']=='SUCCEEDED' and not state['calls'];unchanged()


def _combined_API_payload(pool):
    api=Path.home()/'Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-api-20261015-r4/app'
    names_key='upstreams.v3_shared_data.shared_data.names'
    prior_names=sys.modules.get(names_key)
    names_spec=importlib.util.spec_from_file_location(names_key,api/'upstreams/v3_shared_data/shared_data/names.py')
    names=importlib.util.module_from_spec(names_spec);names_spec.loader.exec_module(names)
    sys.modules[names_key]=names
    try:
        spec=importlib.util.spec_from_file_location('_combined_real_API_mapper',api/'domains/preselection_materializer.py')
        mapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(mapper)
    finally:
        if prior_names is None:sys.modules.pop(names_key,None)
        else:sys.modules[names_key]=prior_names
    spec=importlib.util.spec_from_file_location('_combined_real_API_store',api/'infrastructure/preselection_pool_store.py')
    store_module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=store_module;spec.loader.exec_module(store_module)
    spec=importlib.util.spec_from_file_location('_combined_existing_publish_orchestrator',COMBINED_H/'PUBLICATION_ORCHESTRATOR_R3.py')
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    payload=mapper.build_shared_hk_0_2_pool(Path('/synthetic/shared'),trade_date=TRADE_DATE,
        signal_date=SIGNAL_DATE,reader=lambda *a,**k:pool)
    assert payload['status']=='STRICT_0_2_READY'
    assert 'signal_date' not in payload and 'target_date' not in payload and 'stage_selection_eligible' not in payload
    policy,proof=_combined_trusted_policy()
    token=policy.encode_proof(proof)
    # Keep scores synthetic while the identity/admission set is actually owned.
    codes=proof['score_coverage']['scoreable_signal_codes'][:100]
    for row,code in zip(pool.rows,codes):
        row['code_norm']=code;row['history_resolution_identity']=__import__('hashlib').sha256(token.encode()).hexdigest()
    pool.run.manifest={'provenance':{'history_resolution_proof':token}}
    # Re-map after binding the synthetic rows to the real allowed-code set.
    payload=mapper.build_shared_hk_0_2_pool(Path('/synthetic/shared'),trade_date=TRADE_DATE,
        signal_date=SIGNAL_DATE,reader=lambda *a,**k:pool)
    payload=publisher.complete_consumer_identity(payload,pool,policy=policy,signal_date=SIGNAL_DATE,target_date=TRADE_DATE)
    # Exercise the existing legacy omission path explicitly after the new thin
    # publisher has established stage eligibility from real trusted admission.
    payload.pop('signal_date');payload.pop('target_date')
    return payload,store_module


@pytest.mark.parametrize('status',['READY','STRICT_0_2_READY','HK_0_2_TOP100_READY'])
def test_combined_API_real_mapper_create_and_main_gate_infers_exact_D1(tmp_path,monkeypatch,status):
    module,registry,store,state,pool,unchanged=_combined_fixture(tmp_path,monkeypatch)
    payload,api_store=_combined_API_payload(pool);payload['status']=status
    api_store.PreselectionPoolStore(registry.data_root).materialize(payload)
    result=registry._verified_formal_pool_reuse(TRADE_DATE)
    assert result['status']=='SUCCEEDED' and result['hk_lane_status']=='READY', {k:v for k,v in payload.items() if k!='rows'}
    assert result['producer_called'] is False and not state['calls'];unchanged()


@pytest.mark.parametrize('case',['partial','top_signal','top_target','row_signal_missing','row_signal_mixed',
    'row_target_mixed','old_signal','missing_row','wrong_run','wrong_receipt','wrong_manifest',
    'wrong_artifact','wrong_code','wrong_rank','wrong_score','nonfinite_score','wrong_proof'])
def test_combined_API_publication_invalid_fields_do_not_pass_main_gate(tmp_path,monkeypatch,case):
    module,registry,store,state,pool,unchanged=_combined_fixture(tmp_path,monkeypatch)
    payload,api_store=_combined_API_payload(pool)
    if case=='partial':payload['status']='PARTIAL_WITH_ROWS'
    elif case=='top_signal':payload['signal_date']='20261014'
    elif case=='top_target':payload['target_date']='20261015'
    elif case=='row_signal_missing':payload['rows'][0].pop('signal_date')
    elif case=='row_signal_mixed':payload['rows'][0]['signal_date']='20261014'
    elif case=='row_target_mixed':payload['rows'][0]['target_date']='20261015'
    elif case=='old_signal':
        for row in payload['rows']:row['signal_date']='20261014'
    elif case=='missing_row':payload['rows'].pop()
    elif case=='wrong_run':payload['source_run_id']='foreign'
    elif case=='wrong_receipt':payload['source_receipt_sha256']='f'*64
    elif case=='wrong_manifest':payload['source_manifest_sha256']='f'*64
    elif case=='wrong_artifact':payload['source_sha256']='f'*64
    elif case=='wrong_code':payload['rows'][0]['code_norm']='HK.09999'
    elif case=='wrong_rank':payload['rows'][0]['rank']='2'
    elif case=='wrong_score':payload['rows'][0]['pool_score']=0.11
    elif case=='nonfinite_score':payload['rows'][0]['pool_score']='nan'
    elif case=='wrong_proof':payload['rows'][0]['history_resolution_identity']='f'*64
    # Store validates the source contract before the main's stronger gate. Both
    # closed boundaries are acceptable; neither may enter any producer.
    try:api_store.PreselectionPoolStore(registry.data_root).materialize(payload)
    except ValueError:
        assert not state['calls'];unchanged();return
    result=registry._verified_formal_pool_reuse(TRADE_DATE)
    assert result['status']=='FAILED' and result['hk_lane_status']=='QUARANTINED'
    assert result['producer_called'] is False and not state['calls'];unchanged()


from functools import lru_cache

@lru_cache(maxsize=1)
def _combined_trusted_policy():
    path=Path(os.environ.get('V4_HK_COMBINED_SHARED_ROOT',COMBINED_H/'isolated_loader_projection_package'))/'shared_data/hk_history_resolution.py'
    spec=importlib.util.spec_from_file_location('_combined_owned_admission_policy',path)
    resolver=importlib.util.module_from_spec(spec);spec.loader.exec_module(resolver)
    # The standalone loader needs the unchanged exact master dependency beside
    # its source. The projection fixture below gives it a full code-only tree.
    owner=Path.home()/'Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2'
    policy=resolver.ResolutionPolicy(owner,pointer_path=COMBINED_H/'history_resolution_latest.combined.prepared.json')
    return policy,policy._trusted_score_proof(SIGNAL_DATE)


@lru_cache(maxsize=1)
def _combined_actual_loader():
    policy_name='infrastructure.isolated_import_policy'
    previous=sys.modules.get(policy_name)
    spec=importlib.util.spec_from_file_location(policy_name,COMBINED_BASE/'infrastructure/isolated_import_policy.py')
    policy=importlib.util.module_from_spec(spec);sys.modules[policy_name]=policy;spec.loader.exec_module(policy)
    try:
        name='_combined_immutable_main_loader'
        spec=importlib.util.spec_from_file_location(name,COMBINED_BASE/'infrastructure/isolated_package_loader.py')
        loader=importlib.util.module_from_spec(spec);sys.modules[name]=loader;spec.loader.exec_module(loader)
    finally:
        if previous is None:sys.modules.pop(policy_name,None)
        else:sys.modules[policy_name]=previous
    return loader


def _combined_projection_shared():
    return Path(os.environ.get('V4_HK_COMBINED_SHARED_ROOT',COMBINED_H/'isolated_loader_projection_package'))


def test_combined_actual_main_isolated_loader_accepts_real_proof_rejects_00165(monkeypatch):
    import copy,hashlib
    loader=_combined_actual_loader()
    before=list(sys.path)
    shared_before={k:v for k,v in sys.modules.items() if k=='shared_data' or k.startswith('shared_data.')}
    module=loader.load_isolated_package_module(_combined_projection_shared(),package_directory='shared_data',
        module_leaf='hk_0_2',namespace_prefix='hk_history_cache_gate')
    root=Path.home()/'Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'
    monkeypatch.setenv('V4_HK_HISTORY_RESOLUTION_POINTER',str(COMBINED_H/'history_resolution_latest.combined.prepared.json'))
    policy=module.policy_for_shared(root)
    for signal in ['20261014','20261015']:
        proof=policy._trusted_score_proof(signal);token=policy.encode_proof(proof)
        chosen=proof['score_coverage']['scoreable_signal_codes'][0]
        assert policy.verify_proof(token,end=signal,codes=[chosen])==proof
        forged=copy.deepcopy(proof);held='HK.00165'
        forged['excluded_codes'].remove(held);forged['allowed_codes'].append(held);forged['allowed_codes'].sort();forged['excluded_code_count']-=1
        forged['score_coverage']['quality_quarantined_codes'].remove(held)
        forged['score_coverage']['scoreable_signal_codes'].append(held);forged['score_coverage']['scoreable_signal_codes'].sort()
        with pytest.raises(Exception,match='HK_HISTORY_RESOLUTION_SCORE_ADMISSION_MISMATCH'):
            policy.verify_proof(policy.encode_proof(forged),end=signal,codes=[held])
    assert sys.path==before
    assert {k:v for k,v in sys.modules.items() if k=='shared_data' or k.startswith('shared_data.')}==shared_before


@pytest.mark.parametrize('existing_slot',[False,True])
def test_combined_real_master_first_reader_missing_slot_is_retried_only_when_absent(tmp_path,monkeypatch,existing_slot):
    module,registry,store,state,pool,unchanged=_combined_fixture(tmp_path,monkeypatch,'upstream_failure')
    loader=importlib.import_module('infrastructure.isolated_package_loader')
    actual=_combined_actual_loader()
    monkeypatch.setattr(loader,'load_isolated_package_module',actual.load_isolated_package_module)
    registry.shared_package_root=_combined_projection_shared()
    registry.shared_data_root.mkdir(parents=True)
    if existing_slot:
        shared_module=actual.load_isolated_package_module(registry.shared_package_root,package_directory='shared_data',module_leaf='hk_0_2',namespace_prefix='hk_history_cache_gate')
        # No security master and no run files: an existing broken slot is not
        # a license to re-enter the producer, regardless of read order.
        (registry.shared_data_root/'latest.json').write_text(json.dumps({
            'schema_version':shared_module.SafeRootStore(registry.shared_data_root)._load_latest()['schema_version'],
            'entries':{TRADE_DATE+'/'+HK_0_2_ROLE:{'run_id':'broken-existing-run'}}}))
    assert not (registry.shared_data_root/'assets/hk_security_master').exists()
    result=registry._preselection_pools(SimpleNamespace(business_date=SIGNAL_DATE,target_date=TRADE_DATE))
    assert result['status']=='FAILED' and result['A_producer_called'] is False
    if existing_slot:
        assert not state['calls'] and result['failure_class']=='HK_HISTORY_RESOLUTION_CACHE_REJECTED'
    else:
        assert state['calls']==['scripts.update_hk_0_2_panel'] and result['failure_class']=='UPSTREAM_NOT_READY'
    assert 'dynamic import' not in result['reason'];unchanged()
