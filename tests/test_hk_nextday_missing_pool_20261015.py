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
            {"trade_date": trade_date, "run_id": "isolated-security-master"},
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


def test_canonical_missing_hk_source_follows_existing_producer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader_module = _real_shared_hk_reader(monkeypatch)
    observed = _patch_canonical_exact_sources(monkeypatch, reader_module)
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

    assert result["status"] == "SUCCEEDED"
    assert "scripts.materialize_hk_0_2" in [module for module, _args in calls]
    hk_call = next(
        args for module, args in calls if module == "scripts.materialize_hk_0_2"
    )
    assert hk_call[hk_call.index("--target-date") + 1] == observed["target_date"]
    assert hk_call[hk_call.index("--signal-date") + 1] == observed["expected_signal_date"]
    assert observed == {
        "a_target_date": TRADE_DATE,
        "a_signal_date": SIGNAL_DATE,
        "target_date": TRADE_DATE,
        "expected_signal_date": SIGNAL_DATE,
    }
    assert all(
        result.get(flag) is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )


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
