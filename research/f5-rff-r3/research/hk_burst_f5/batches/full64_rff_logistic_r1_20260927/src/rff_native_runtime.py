"""Bounded native/reference adapter for the frozen F5 RFF logistic route.

This helper implements only the interface consumed by the accepted owner and
resource-tree monitor.  It binds the already accepted Factor Factory Runtime
V1 Python and validates the known training/evaluation imports. It does not
call an optimizer or metric, read candidate inputs, or install dependencies.
Import readiness is not a distribution/ABI approval or a research release.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
RUNTIME_CONTRACT_PATH = ROOT / "runtime/factor_factory_runtime_v1/contracts/FACTOR_FACTORY_RUNTIME_V1.json"
RUNTIME_CONTRACT_SHA256 = "9b58cdbaab276e6d75192e954385475c68de1bba8ef91880db6e20fb68a5d3af"
RUNTIME_ID = "FACTOR_FACTORY_RUNTIME_V1_RFF_DEPENDENCY_MAINTENANCE_R1_20260928"
PYTHON_PATH = "/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python"
ENVIRONMENT_POLICY = "REUSE_EXISTING_NO_INSTALL_DURING_RESEARCH_RUN"
REQUIRED_IMPORTS = ("numpy", "pandas", "scipy", "scipy.optimize", "sklearn", "sklearn.metrics")
REQUIRED_DEPENDENCY_VERSIONS = {"scikit-learn": "1.8.0"}


class RFFNativeRuntimeError(RuntimeError):
    """Raised when the bound RFF runtime or its direct imports do not match."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_runtime_contract(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    runtime_path = Path(path).expanduser()
    if runtime_path.is_symlink() or not runtime_path.is_file():
        raise RFFNativeRuntimeError("RFF_RUNTIME_CONTRACT_MISSING_OR_SYMLINK")
    raw = runtime_path.read_bytes()
    actual_sha256 = _sha256_bytes(raw)
    if actual_sha256 != expected_sha256 or actual_sha256 != RUNTIME_CONTRACT_SHA256:
        raise RFFNativeRuntimeError("RFF_RUNTIME_CONTRACT_SHA_MISMATCH")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RFFNativeRuntimeError("RFF_RUNTIME_CONTRACT_UNREADABLE") from exc
    if not isinstance(document, dict):
        raise RFFNativeRuntimeError("RFF_RUNTIME_CONTRACT_NOT_OBJECT")
    if document.get("runtime_id") != RUNTIME_ID or document.get("status") != "FROZEN":
        raise RFFNativeRuntimeError("RFF_RUNTIME_CONTRACT_IDENTITY_MISMATCH")
    python = document.get("python")
    if not isinstance(python, Mapping):
        raise RFFNativeRuntimeError("RFF_RUNTIME_PYTHON_SECTION_MISSING")
    if (python.get("path") != PYTHON_PATH
            or python.get("environment_policy") != ENVIRONMENT_POLICY):
        raise RFFNativeRuntimeError("RFF_RUNTIME_PYTHON_BINDING_MISMATCH")
    return document


def native_spec_from_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the route reference and return the owner/resource-tree spec."""
    if (contract.get("schema") != "F5_FULL64_RFF_NATIVE_REFERENCE_RUNTIME_V1"
            or contract.get("route_id") != "F5_FULL64_RFF_LOGISTIC_R1_20260927"):
        raise RFFNativeRuntimeError("RFF_NATIVE_REFERENCE_IDENTITY_MISMATCH")
    runtime = contract.get("runtime_contract")
    if not isinstance(runtime, Mapping):
        raise RFFNativeRuntimeError("RFF_RUNTIME_REFERENCE_MISSING")
    expected_runtime = {
        "path": str(RUNTIME_CONTRACT_PATH),
        "sha256": RUNTIME_CONTRACT_SHA256,
        "runtime_id": RUNTIME_ID,
        "python_path": PYTHON_PATH,
        "environment_policy": ENVIRONMENT_POLICY,
    }
    if dict(runtime) != expected_runtime:
        raise RFFNativeRuntimeError("RFF_RUNTIME_REFERENCE_MISMATCH")
    if tuple(contract.get("direct_imports", ())) != REQUIRED_IMPORTS:
        raise RFFNativeRuntimeError("RFF_DIRECT_IMPORT_SET_MISMATCH")
    if contract.get("dependency_versions") != REQUIRED_DEPENDENCY_VERSIONS:
        raise RFFNativeRuntimeError("RFF_DEPENDENCY_VERSION_SET_MISMATCH")
    if contract.get("native_library_policy") != "NO_LIGHTGBM_OR_LIBOMP_BINDING; USE_THE_FROZEN_RFF_SCIPY_ROUTE":
        raise RFFNativeRuntimeError("RFF_NATIVE_LIBRARY_POLICY_MISMATCH")
    spawn = contract.get("spawn_environment")
    if not isinstance(spawn, Mapping) or dict(spawn) != {
        "dyld_library_path": "",
        "inherit_custom_dyld_library_path": False,
        "restore_parent_environment_after_process_start": True,
        "worker_fit_or_input_read": False,
    }:
        raise RFFNativeRuntimeError("RFF_SPAWN_ENVIRONMENT_POLICY_MISMATCH")
    _read_runtime_contract(runtime["path"], runtime["sha256"])
    return {
        "runtime_contract_path": runtime["path"],
        "runtime_contract_sha256": runtime["sha256"],
        "runtime_id": runtime["runtime_id"],
        "environment_policy": runtime["environment_policy"],
        "python_executable_path": runtime["python_path"],
        "python_prefix_path": str(Path(runtime["python_path"]).expanduser().absolute().parent.parent.resolve()),
        "direct_imports": list(REQUIRED_IMPORTS),
        "dependency_versions": dict(REQUIRED_DEPENDENCY_VERSIONS),
        # The accepted resource_tree passes this value to the helper's spawn
        # context manager.  Empty means no custom DYLD library directory.
        "dyld_library_path": "",
    }


def validate_native_files(spec: Mapping[str, Any], *, require_macos: bool = False) -> dict[str, Any]:
    """Verify the accepted interpreter and importable direct RFF dependencies."""
    if require_macos and platform.system() != "Darwin":
        raise RFFNativeRuntimeError(f"RFF_RUNTIME_PLATFORM_NOT_MACOS:{platform.system()}")
    if (spec.get("runtime_contract_path") != str(RUNTIME_CONTRACT_PATH)
            or spec.get("runtime_contract_sha256") != RUNTIME_CONTRACT_SHA256
            or spec.get("runtime_id") != RUNTIME_ID
            or spec.get("environment_policy") != ENVIRONMENT_POLICY
            or tuple(spec.get("direct_imports", ())) != REQUIRED_IMPORTS
            or spec.get("dependency_versions") != REQUIRED_DEPENDENCY_VERSIONS
            or spec.get("dyld_library_path") != ""):
        raise RFFNativeRuntimeError("RFF_NATIVE_SPEC_BINDING_MISMATCH")
    _read_runtime_contract(spec["runtime_contract_path"], str(spec["runtime_contract_sha256"]))

    expected_executable = Path(str(spec.get("python_executable_path", ""))).expanduser().resolve()
    actual_executable = Path(sys.executable).resolve()
    if expected_executable != Path(PYTHON_PATH).expanduser().resolve() or actual_executable != expected_executable:
        raise RFFNativeRuntimeError(f"RFF_PYTHON_EXECUTABLE_MISMATCH:{actual_executable}:{expected_executable}")
    # A venv binary can be a symlink to a shared base interpreter. Its target
    # does not determine the selected virtual environment's package prefix.
    expected_prefix = Path(PYTHON_PATH).expanduser().absolute().parent.parent.resolve()
    actual_prefix = Path(sys.prefix).resolve()
    if (Path(str(spec.get("python_prefix_path", ""))).expanduser().resolve() != expected_prefix
            or actual_prefix != expected_prefix):
        raise RFFNativeRuntimeError(f"RFF_PYTHON_PREFIX_MISMATCH:{actual_prefix}:{expected_prefix}")

    imported: dict[str, Any] = {}
    for module_name in REQUIRED_IMPORTS:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RFFNativeRuntimeError(f"RFF_DIRECT_IMPORT_FAILED:{module_name}:{type(exc).__name__}") from exc
        module_file = getattr(module, "__file__", None)
        if not module_file:
            raise RFFNativeRuntimeError(f"RFF_DIRECT_IMPORT_PATH_MISSING:{module_name}")
        resolved_module_file = Path(module_file).resolve()
        try:
            resolved_module_file.relative_to(expected_prefix)
        except ValueError as exc:
            raise RFFNativeRuntimeError(f"RFF_DIRECT_IMPORT_OUTSIDE_RUNTIME:{module_name}:{resolved_module_file}") from exc
        if not resolved_module_file.is_file():
            raise RFFNativeRuntimeError(f"RFF_DIRECT_IMPORT_FILE_MISSING:{module_name}")
        imported[module_name] = {
            "path": str(resolved_module_file),
            "version": str(getattr(module, "__version__", "")),
            "sha256": _sha256_file(resolved_module_file),
        }
        if module_name == "sklearn" and getattr(module, "__version__", None) != REQUIRED_DEPENDENCY_VERSIONS["scikit-learn"]:
            raise RFFNativeRuntimeError("RFF_SKLEARN_VERSION_MISMATCH")
        if module_name == "sklearn.metrics":
            if not callable(getattr(module, "average_precision_score", None)):
                raise RFFNativeRuntimeError("RFF_SKLEARN_AP_UNAVAILABLE")
            imported[module_name]["average_precision_score_callable"] = True
    optimize = importlib.import_module("scipy.optimize")
    minimize = getattr(optimize, "minimize", None)
    if not callable(minimize):
        raise RFFNativeRuntimeError("RFF_SCIPY_OPTIMIZE_MINIMIZE_UNAVAILABLE")
    optimize_path = Path(str(getattr(optimize, "__file__", ""))).resolve()
    try:
        optimize_path.relative_to(expected_prefix)
    except ValueError as exc:
        raise RFFNativeRuntimeError(f"RFF_DIRECT_IMPORT_OUTSIDE_RUNTIME:scipy.optimize:{optimize_path}") from exc
    imported["scipy.optimize"]["minimize_callable"] = True
    return {
        "runtime_contract_path": str(RUNTIME_CONTRACT_PATH),
        "runtime_contract_sha256": RUNTIME_CONTRACT_SHA256,
        "runtime_id": RUNTIME_ID,
        "python_executable": str(actual_executable),
        "python_executable_resolved": str(actual_executable),
        "python_executable_launch_path": str(Path(sys.executable).absolute()),
        "python_prefix": str(actual_prefix),
        "python_version": platform.python_version(),
        "direct_imports": imported,
        "custom_dyld_library_path": "NOT_USED_BY_RFF_ROUTE",
        # This helper observes a few module files, not every wheel/native image.
        # The original Runtime maintenance release must approve those separately.
        "dependency_distribution_lock_verified": False,
    }


def verify_child_launch_environment(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Check spawned child identity without fitting or reading route inputs."""
    if os.environ.get("DYLD_LIBRARY_PATH") not in (None, ""):
        raise RFFNativeRuntimeError("RFF_CHILD_CUSTOM_DYLD_LIBRARY_PATH_PRESENT")
    observed = validate_native_files(spec, require_macos=False)
    observed["child_dyld_library_path"] = os.environ.get("DYLD_LIBRARY_PATH")
    return observed


@contextlib.contextmanager
def process_local_dyld_for_spawn(dyld_library_path: str):
    """Clear legacy custom DYLD state only for spawn, then restore the parent."""
    if str(dyld_library_path) != "":
        raise RFFNativeRuntimeError("RFF_CUSTOM_DYLD_PATH_NOT_ALLOWED")
    key = "DYLD_LIBRARY_PATH"
    old_present = key in os.environ
    old_value = os.environ.get(key)
    os.environ.pop(key, None)
    try:
        yield
    finally:
        if old_present:
            os.environ[key] = old_value if old_value is not None else ""
        else:
            os.environ.pop(key, None)
