"""Spawn target for the RFF native-runtime regression; stops before input reads."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_exact(path: Path, module_name: str, expected_sha256: str) -> ModuleType:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError(f"SENTINEL_SOURCE_SHA_MISMATCH:{module_name}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"SENTINEL_SOURCE_LOAD_FAILED:{module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def run_rff_worker_until_pre_fit_boundary(payload: Mapping[str, Any]) -> None:
    """Run the actual RFF worker until its first-input loader, then stop."""
    helper_record = payload["executable_helpers"]["native_runtime"]
    helper_path = Path(helper_record["path"]).resolve(strict=True)
    helper = _load_exact(helper_path, "rff_native_runtime_pre_fit_sentinel", helper_record["sha256"])
    child_identity = helper.verify_child_launch_environment(payload["native_spec"])

    code_files = payload["code_files"]
    candidate_record = code_files["candidate_worker"]
    candidate_path = Path(candidate_record["path"]).resolve(strict=True)
    route_worker_record = code_files["rff_worker"]
    route_worker_path = Path(route_worker_record["path"]).resolve(strict=True)
    for item in (candidate_record, route_worker_record, *code_files.values()):
        parent = str(Path(item["path"]).resolve(strict=True).parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)

    # Import the lazily selected original evaluator now, without calling any
    # selector, probability metric or label decoder. Otherwise a pre-input
    # sentinel can pass and still miss a dependency needed after prediction.
    score_record = code_files["score_aware_metrics"]
    score_path = Path(score_record["path"]).resolve(strict=True)
    score_module = _load_exact(score_path, "score_aware_metrics", score_record["sha256"])
    evaluator = score_module.frozen_metrics()
    evaluator_path = Path(score_module.FROZEN_METRICS_PATH).resolve(strict=True)
    if (Path(str(getattr(evaluator, "__file__", ""))).resolve() != evaluator_path
            or _sha256_file(evaluator_path) != score_module.FROZEN_METRICS_SHA256):
        raise RuntimeError("SENTINEL_EVALUATOR_SOURCE_MISMATCH")
    for function_name in ("select_top3", "paired_precision", "probability_metrics", "arm_metrics"):
        if not callable(getattr(evaluator, function_name, None)):
            raise RuntimeError(f"SENTINEL_EVALUATOR_API_MISSING:{function_name}")

    candidate_worker = _load_exact(candidate_path, "candidate_worker", candidate_record["sha256"])
    marker_path = Path(str(payload["prefit_boundary_marker_path"]))

    def stop_before_any_input_read(_worker_payload: Mapping[str, Any]) -> None:
        marker = {
            "schema": "F5_RFF_WORKER_PREFIT_BOUNDARY_SENTINEL_V1",
            "status": "STOPPED_BEFORE_FIRST_BOUND_INPUT_READ",
            "python_executable": child_identity["python_executable"],
            "python_prefix": child_identity["python_prefix"],
            "python_version": child_identity["python_version"],
            "direct_imports": child_identity["direct_imports"],
            "evaluator_imports_verified": True,
            "evaluator_source_sha256": score_module.FROZEN_METRICS_SHA256,
            "evaluator_source_path": str(evaluator_path),
            "original_input_loader_called": False,
            "training_input_reads": 0,
            "candidate_fit_calls": 0,
            "candidate_predict_calls": 0,
            "evaluation_truth_decodes": 0,
            "registry_writes": 0,
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        with marker_path.open("xb") as stream:
            stream.write(json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            stream.flush()
        raise RuntimeError("RFF_PREFIT_WORKER_BOUNDARY_SENTINEL")

    candidate_worker._load_bound_inputs = stop_before_any_input_read
    worker = _load_exact(route_worker_path, "rff_worker", route_worker_record["sha256"])
    worker.run_candidate_worker(payload)
