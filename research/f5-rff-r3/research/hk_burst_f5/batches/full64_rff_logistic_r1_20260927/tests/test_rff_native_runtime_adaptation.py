from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
BATCH = ROOT / "research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927"
HANDOFF = ROOT / "handoffs/F5_RFF_RESUME_EXECUTION_20260928"
EXECUTION_ID = "F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01"
NATIVE_REFERENCE_PATH = BATCH / "contracts/RFF_NATIVE_REFERENCE_RUNTIME_V1_20260928.json"
NATIVE_RUNTIME_PATH = BATCH / "src/rff_native_runtime.py"
RESOURCE_TREE_PATH = ROOT / "research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/src/resource_tree.py"
SPAWN_TARGET_PATH = Path(__file__).with_name("rff_worker_fit_boundary_sentinel.py")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _native_spec():
    helper = _load_module(NATIVE_RUNTIME_PATH, "rff_native_runtime_test")
    reference = json.loads(NATIVE_REFERENCE_PATH.read_text(encoding="utf-8"))
    return helper, helper.native_spec_from_contract(reference)


def test_rff_native_reference_uses_accepted_runtime_and_only_checks_imports():
    helper, native_spec = _native_spec()
    observed = helper.validate_native_files(native_spec, require_macos=False)
    assert observed["runtime_contract_sha256"] == "9b58cdbaab276e6d75192e954385475c68de1bba8ef91880db6e20fb68a5d3af"
    assert Path(observed["python_executable"]).resolve() == Path(helper.PYTHON_PATH).resolve()
    assert Path(observed["python_prefix"]) == Path(helper.PYTHON_PATH).absolute().parent.parent.resolve()
    assert set(observed["direct_imports"]) == {"numpy", "pandas", "scipy", "scipy.optimize", "sklearn", "sklearn.metrics"}
    assert observed["direct_imports"]["scipy.optimize"]["minimize_callable"] is True
    assert "lightgbm" not in observed["direct_imports"]
    assert observed["direct_imports"]["sklearn"]["version"] == "1.8.0"
    assert observed["direct_imports"]["sklearn.metrics"]["average_precision_score_callable"] is True

    wrong_interpreter = dict(native_spec)
    wrong_interpreter["python_executable_path"] = "/usr/bin/python3"
    with pytest.raises(helper.RFFNativeRuntimeError, match="RFF_PYTHON_EXECUTABLE_MISMATCH"):
        helper.validate_native_files(wrong_interpreter, require_macos=False)

    old_dyld = os.environ.get("DYLD_LIBRARY_PATH")
    os.environ["DYLD_LIBRARY_PATH"] = "RFF_TEST_ONLY_LEGACY_PATH"
    try:
        with helper.process_local_dyld_for_spawn(native_spec["dyld_library_path"]):
            assert "DYLD_LIBRARY_PATH" not in os.environ
        assert os.environ.get("DYLD_LIBRARY_PATH") == "RFF_TEST_ONLY_LEGACY_PATH"
    finally:
        if old_dyld is None:
            os.environ.pop("DYLD_LIBRARY_PATH", None)
        else:
            os.environ["DYLD_LIBRARY_PATH"] = old_dyld


def test_real_resource_tree_spawn_stops_actual_rff_worker_before_input_read(tmp_path: Path):
    # Explicit current metadata identities; never silently reuse stale R3 drafts.
    binding_path = Path(os.environ["F5_RFF_NATIVE_BINDING_PATH"]).resolve(strict=True)
    spec_path = Path(os.environ["F5_RFF_NATIVE_RUN_SPEC_PATH"]).resolve(strict=True)
    assert _sha256_file(binding_path) == os.environ["F5_RFF_NATIVE_BINDING_SHA256"]
    assert _sha256_file(spec_path) == os.environ["F5_RFF_NATIVE_RUN_SPEC_SHA256"]
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert binding["run_spec_sha256"] == _sha256_file(spec_path)
    assert spec["route_id"] == binding["route_id"] and spec["execution_id"] == binding["execution_id"]
    # This evidence root must be created by the logging wrapper before pytest.
    evidence_root = Path(os.environ["F5_RFF_NATIVE_EVIDENCE_ROOT"]).expanduser()
    assert evidence_root.is_absolute() and evidence_root.is_dir() and not evidence_root.is_symlink()
    probe_root = evidence_root / "worker_before_input_probe"
    probe_root.mkdir(exist_ok=False)
    helper, native_spec = _native_spec()
    helper_record = binding["executable_helpers"]["native_runtime"]
    reference_record = binding["executable_helpers"]["native_reference_contract"]
    runtime_record = binding["executable_helpers"]["runtime_contract"]
    resource_record = binding["executable_helpers"]["resource_tree"]
    assert Path(helper_record["path"]).resolve() == NATIVE_RUNTIME_PATH.resolve()
    assert _sha256_file(NATIVE_RUNTIME_PATH) == helper_record["sha256"]
    assert Path(reference_record["path"]).resolve() == NATIVE_REFERENCE_PATH.resolve()
    assert _sha256_file(NATIVE_REFERENCE_PATH) == reference_record["sha256"]
    assert _sha256_file(Path(runtime_record["path"])) == runtime_record["sha256"]
    assert _sha256_file(RESOURCE_TREE_PATH) == resource_record["sha256"]

    resource_parent = str(RESOURCE_TREE_PATH.parent.resolve())
    if resource_parent not in sys.path:
        sys.path.insert(0, resource_parent)
    resource_tree = _load_module(RESOURCE_TREE_PATH, "resource_tree")
    output_root = probe_root / "candidate_output"
    output_root.mkdir()
    start_path = output_root / "CANDIDATE_START_RECEIPT.synthetic.json"
    start_path.write_bytes(b"synthetic prefit sentinel start receipt\n")
    # This probe needs no formal registry bytes or real input path.
    registry_path = probe_root / "synthetic_registry.jsonl"
    registry_path.write_bytes(b"")
    registry_sha_before = _sha256_file(registry_path)
    marker_path = probe_root / "RFF_PREFIT_BOUNDARY_SENTINEL.json"
    worker_payload = {
        "execution_id": binding["execution_id"],
        "code_files": binding["code_files"],
        "source_code_sha256": binding["code_sha256"],
        "executable_helpers": binding["executable_helpers"],
        "input_files": {name: {"path": str(probe_root / "INPUT_MUST_NOT_BE_READ" / str(index)), "sha256": "0" * 64}
                        for index, name in enumerate(binding["input_files"])},
        "training_contract": binding["training_contract"],
        "evaluation_contract": binding["evaluation_contract"],
        "prediction_contract": binding["prediction_contract"],
        "feature_count": binding["feature_count"],
        "output_root": str(output_root),
        "start_receipt_path": str(start_path),
        "start_receipt_sha256": _sha256_file(start_path),
        "run_spec_sha256": _sha256_file(spec_path),
        "input_binding_sha256": _sha256_file(binding_path),
        "native_spec": native_spec,
        "native_runtime_path": str(NATIVE_RUNTIME_PATH),
        "route_source_root": str((BATCH / "src").resolve()),
        "recovery_source_root": str((ROOT / "research/hk_burst_f5/batches/full64_xendcg_r1_20260924/recovery_01/src").resolve()),
        "run_spec": spec,
        "prefit_boundary_marker_path": str(marker_path),
    }
    descriptor = {
        "path": str(SPAWN_TARGET_PATH.resolve()),
        "sha256": _sha256_file(SPAWN_TARGET_PATH),
        "module_name": "rff_worker_fit_boundary_sentinel",
        "callable": "run_rff_worker_until_pre_fit_boundary",
    }
    trace_path = probe_root / "resource_trace.json"
    failure_path = probe_root / "failure.json"
    result = resource_tree.run_spawn_monitored(
        None,
        worker_payload,
        native_spec=native_spec,
        native_runtime_helper_path=NATIVE_RUNTIME_PATH,
        wall_seconds_max=1800.0,
        rss_bytes_max=3221225472,
        threads=4,
        resource_trace_path=trace_path,
        sample_seconds=0.05,
        target_descriptor=descriptor,
        failure_evidence_path=failure_path,
        failure_context={"source_files": {"rff_worker": binding["code_files"]["rff_worker"]}},
    )

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    status = json.loads((output_root / "CANDIDATE_WORKER_STATUS.json").read_text(encoding="utf-8"))
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert result["worker_exitcode"] != 0
    assert result["terminal_reason"] is None
    assert marker["status"] == "STOPPED_BEFORE_FIRST_BOUND_INPUT_READ"
    assert marker["evaluator_imports_verified"] is True
    assert marker["original_input_loader_called"] is False
    assert marker["training_input_reads"] == 0
    assert marker["candidate_fit_calls"] == marker["candidate_predict_calls"] == 0
    assert marker["evaluation_truth_decodes"] == marker["registry_writes"] == 0
    assert status["status"] == "FAILED"
    assert status["fit_calls"] == status["real_fit_returned_count"] == 0
    assert status["fit_call_entered"] is False
    assert status["predict_calls"] == status["evaluation_truth_decodes"] == 0
    assert failure["exception_message"] == "RFF_PREFIT_WORKER_BOUNDARY_SENTINEL"
    assert not (output_root / "CANDIDATE_INPUT_HASH_RECEIPT.json").exists()
    assert not list(output_root.glob("CANDIDATE_FIT_RECEIPT*"))
    assert not list(output_root.glob("CANDIDATE_RESULT_RECEIPT*"))
    assert _sha256_file(registry_path) == registry_sha_before
