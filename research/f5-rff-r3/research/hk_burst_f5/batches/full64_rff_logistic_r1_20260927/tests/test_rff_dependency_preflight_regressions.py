"""Pure synthetic protocol tests. No installed numerical library is imported.

Set F5_RFF_PREFLIGHT_TEST_ROOT to the exact before/after route for red/green.
All import targets, interpreter paths, evaluator files and contracts are fixtures.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROUTE = Path(os.environ.get("F5_RFF_PREFLIGHT_TEST_ROOT", Path(__file__).resolve().parents[1]))
MODULES = ("numpy", "pandas", "scipy", "scipy.optimize", "sklearn", "sklearn.metrics")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    raw = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def never_compute(*args, **kwargs):
    raise AssertionError("Numerical/evaluation execution is forbidden in this fixture")


@pytest.fixture
def environment(tmp_path):
    helper = load(ROUTE / "src/rff_native_runtime.py", "rff_native_fixture")
    prefix = tmp_path / "runtime"
    exe = prefix / "bin/python"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"synthetic interpreter identity; not executable")
    modules = {}
    for name in MODULES:
        file = prefix / "lib" / Path(*name.split(".")) / "__init__.py"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(("# SYNTHETIC MODULE " + name + "\n").encode())
        modules[name] = SimpleNamespace(__file__=str(file), __version__="1.8.0" if name == "sklearn" else "fixture")
    modules["scipy.optimize"].minimize = never_compute
    modules["sklearn.metrics"].average_precision_score = never_compute
    calls = []

    def fake_import(name):
        calls.append(name)
        if name not in modules:
            raise ModuleNotFoundError("No module named '" + name + "'")
        return modules[name]

    helper.importlib = SimpleNamespace(import_module=fake_import)
    helper.sys = SimpleNamespace(executable=str(exe), prefix=str(prefix))
    helper.platform = SimpleNamespace(system=lambda: "Darwin", python_version=lambda: "SYNTHETIC")
    helper.PYTHON_PATH = str(exe)
    helper.RUNTIME_CONTRACT_PATH = tmp_path / "runtime_contract.json"
    document = {
        "runtime_id": helper.RUNTIME_ID, "status": "FROZEN",
        "python": {"path": str(exe), "environment_policy": helper.ENVIRONMENT_POLICY},
    }
    helper.RUNTIME_CONTRACT_PATH.write_text(json.dumps(document), encoding="utf-8")
    helper.RUNTIME_CONTRACT_SHA256 = digest(helper.RUNTIME_CONTRACT_PATH)
    ref = json.loads((ROUTE / "contracts/RFF_NATIVE_REFERENCE_RUNTIME_V1_20260928.json").read_text())
    ref["runtime_contract"].update({
        "path": str(helper.RUNTIME_CONTRACT_PATH), "sha256": helper.RUNTIME_CONTRACT_SHA256,
        "python_path": str(exe),
    })
    return SimpleNamespace(helper=helper, modules=modules, calls=calls, prefix=prefix, exe=exe, reference=ref, tmp=tmp_path)


def validate(env):
    spec = env.helper.native_spec_from_contract(env.reference)
    return env.helper.validate_native_files(spec)


def test_required_imports_cover_worker_and_score_helper(environment):
    assert set(environment.helper.REQUIRED_IMPORTS) == set(MODULES)


@pytest.mark.parametrize("missing", MODULES)
def test_each_missing_dependency_rejected_without_numeric_calls(environment, missing):
    del environment.modules[missing]
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_DIRECT_IMPORT_FAILED"):
        validate(environment)


def test_valid_complete_dependency_imports_do_not_compute(environment):
    result = validate(environment)
    assert set(result["direct_imports"]) == set(MODULES)
    assert result["direct_imports"]["sklearn.metrics"]["average_precision_score_callable"] is True
    assert result["direct_imports"]["sklearn"]["version"] == "1.8.0"


@pytest.mark.parametrize("value", [None, "1.7.0", "1.8.0.dev0", "", 180])
def test_unapproved_sklearn_version_rejected(environment, value):
    environment.modules["sklearn"].__version__ = value
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_SKLEARN_VERSION_MISMATCH"):
        validate(environment)


@pytest.mark.parametrize("value", [None, False, 1, "callable"])
def test_missing_average_precision_callable_rejected(environment, value):
    environment.modules["sklearn.metrics"].average_precision_score = value
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_SKLEARN_AP_UNAVAILABLE"):
        validate(environment)


@pytest.mark.parametrize("name", MODULES)
def test_dependency_outside_selected_runtime_rejected(environment, name):
    outside = environment.tmp / "foreign" / (name + ".py")
    outside.parent.mkdir(exist_ok=True)
    outside.write_bytes(b"# synthetic foreign source")
    environment.modules[name].__file__ = str(outside)
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_DIRECT_IMPORT_OUTSIDE_RUNTIME"):
        validate(environment)


def test_known_dependency_missing_file_rejected(environment):
    Path(environment.modules["sklearn"].__file__).unlink()
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_DIRECT_IMPORT_FILE_MISSING"):
        validate(environment)


def test_observed_module_hashes_are_from_real_fixture_bytes(environment):
    result = validate(environment)
    for name in MODULES:
        assert result["direct_imports"][name]["sha256"] == digest(environment.modules[name].__file__)
    # Observation is not an approval of these fixture distributions.
    assert result["dependency_distribution_lock_verified"] is False


def test_symlinked_venv_binary_does_not_replace_venv_prefix(environment):
    base = environment.tmp / "base/bin/python"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"# synthetic shared base interpreter")
    environment.exe.unlink()
    environment.exe.symlink_to(base)
    result = validate(environment)
    assert result["python_prefix"] == str(environment.prefix.resolve())
    assert result["python_executable_resolved"] == str(base.resolve())


def test_other_venv_with_same_base_binary_rejected(environment):
    base = environment.tmp / "base/bin/python"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"# synthetic base")
    environment.exe.unlink()
    environment.exe.symlink_to(base)
    other = environment.tmp / "other/bin/python"
    other.parent.mkdir(parents=True)
    other.symlink_to(base)
    environment.helper.sys.executable = str(other)
    environment.helper.sys.prefix = str(other.parent.parent)
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_PYTHON_PREFIX_MISMATCH"):
        validate(environment)


def test_reference_cannot_drop_sklearn_version_requirement(environment):
    environment.reference.pop("dependency_versions", None)
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_DEPENDENCY_VERSION_SET_MISMATCH"):
        environment.helper.native_spec_from_contract(environment.reference)


def test_spec_cannot_drop_sklearn_version_requirement(environment):
    spec = environment.helper.native_spec_from_contract(environment.reference)
    spec.pop("dependency_versions", None)
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_NATIVE_SPEC_BINDING_MISMATCH"):
        environment.helper.validate_native_files(spec)


def test_runtime_identity_and_file_hash_still_checked(environment):
    environment.helper.RUNTIME_CONTRACT_PATH.write_text("{}")
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_RUNTIME_CONTRACT_SHA_MISMATCH"):
        validate(environment)


def test_wrong_interpreter_still_rejected(environment):
    environment.helper.sys.executable = str(environment.tmp / "wrong_python")
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_PYTHON_EXECUTABLE_MISMATCH"):
        validate(environment)


def test_missing_optimizer_still_rejected(environment):
    environment.modules["scipy.optimize"].minimize = None
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_SCIPY_OPTIMIZE_MINIMIZE_UNAVAILABLE"):
        validate(environment)


def test_parent_dyld_is_restored_on_exception(environment, monkeypatch):
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "SYNTHETIC_OLD_PATH")
    with pytest.raises(RuntimeError, match="probe abort"):
        with environment.helper.process_local_dyld_for_spawn(""):
            assert "DYLD_LIBRARY_PATH" not in os.environ
            raise RuntimeError("probe abort")
    assert os.environ["DYLD_LIBRARY_PATH"] == "SYNTHETIC_OLD_PATH"


def test_child_rejects_inherited_custom_dyld(environment, monkeypatch):
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "SYNTHETIC_OLD_PATH")
    spec = environment.helper.native_spec_from_contract(environment.reference)
    with pytest.raises(environment.helper.RFFNativeRuntimeError, match="RFF_CHILD_CUSTOM_DYLD"):
        environment.helper.verify_child_launch_environment(spec)


@pytest.fixture
def sentinel_fixture(tmp_path, monkeypatch):
    module = load(ROUTE / "tests/rff_worker_fit_boundary_sentinel.py", "rff_sentinel_fixture")
    source = tmp_path / "fixture_sources"
    source.mkdir()
    files = {
        "native_runtime": ("native.py", "def verify_child_launch_environment(spec):\n    return {'python_executable':'fixture', 'python_prefix':'fixture', 'python_version':'fixture', 'direct_imports':{}}\n"),
        "candidate_worker": ("candidate_worker.py", "def _load_bound_inputs(payload):\n    raise AssertionError('REAL INPUT LOADER FORBIDDEN')\n"),
        "rff_worker": ("rff_worker.py", "def run_candidate_worker(payload):\n    import candidate_worker\n    candidate_worker._load_bound_inputs(payload)\n"),
    }
    records = {}
    for role, (name, text) in files.items():
        path = source / name
        path.write_text(text)
        records[role] = {"path": str(path), "sha256": digest(path)}
    metric = source / "frozen_fixture_metrics.py"
    metric.write_text("# synthetic evaluator module, no numeric implementation\n")
    score = source / "score_aware_metrics.py"
    # callable methods must never be executed by the sentinel.
    score.write_text(
        "from types import SimpleNamespace\n"
        f"from pathlib import Path\nFROZEN_METRICS_PATH = Path({str(metric)!r})\n"
        f"FROZEN_METRICS_SHA256 = {digest(metric)!r}\n"
        "def forbidden(*args, **kwargs):\n    raise AssertionError('EVALUATION FORBIDDEN')\n"
        "def frozen_metrics():\n    return SimpleNamespace(__file__=str(FROZEN_METRICS_PATH), select_top3=forbidden, paired_precision=forbidden, probability_metrics=forbidden, arm_metrics=forbidden)\n"
    )
    records["score_aware_metrics"] = {"path": str(score), "sha256": digest(score)}
    for name in ("candidate_worker", "rff_worker", "score_aware_metrics", "rff_native_runtime_pre_fit_sentinel"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(source))
    # Track additions so fixture modules cannot survive the test.
    existing = dict(sys.modules)
    payload = {"executable_helpers":{"native_runtime":records.pop("native_runtime")},
               "native_spec":{}, "code_files":records,
               "prefit_boundary_marker_path":str(tmp_path / "marker.json")}
    yield SimpleNamespace(module=module,payload=payload,score=score,metric=metric,tmp=tmp_path)
    for name in ("candidate_worker", "rff_worker", "score_aware_metrics", "rff_native_runtime_pre_fit_sentinel"):
        if name in existing: sys.modules[name] = existing[name]
        else: sys.modules.pop(name, None)


def test_sentinel_covers_lazy_evaluator_before_first_input(sentinel_fixture):
    f = sentinel_fixture
    with pytest.raises(RuntimeError, match="RFF_PREFIT_WORKER_BOUNDARY_SENTINEL"):
        f.module.run_rff_worker_until_pre_fit_boundary(f.payload)
    marker = json.loads(Path(f.payload["prefit_boundary_marker_path"]).read_text())
    assert marker["evaluator_imports_verified"] is True
    assert marker["evaluator_source_sha256"] == digest(f.metric)
    assert marker["training_input_reads"] == marker["candidate_fit_calls"] == marker["evaluation_truth_decodes"] == 0


def test_lazy_evaluator_import_failure_is_not_misreported_as_boundary_success(sentinel_fixture):
    f = sentinel_fixture
    f.score.write_text("def frozen_metrics():\n    raise ModuleNotFoundError('SYNTHETIC_LATE_EVALUATOR_DEPENDENCY')\n")
    f.payload["code_files"]["score_aware_metrics"]["sha256"] = digest(f.score)
    with pytest.raises(ModuleNotFoundError, match="SYNTHETIC_LATE_EVALUATOR_DEPENDENCY"):
        f.module.run_rff_worker_until_pre_fit_boundary(f.payload)
    assert not Path(f.payload["prefit_boundary_marker_path"]).exists()


def test_sentinel_rejects_tampered_evaluator_source(sentinel_fixture):
    f = sentinel_fixture
    f.metric.write_text("# changed synthetic metrics source\n")
    with pytest.raises(RuntimeError, match="SENTINEL_EVALUATOR_SOURCE_MISMATCH"):
        f.module.run_rff_worker_until_pre_fit_boundary(f.payload)
    assert not Path(f.payload["prefit_boundary_marker_path"]).exists()


def test_local_native_probe_does_not_hash_formal_registry():
    text = (ROUTE / "tests/test_rff_native_runtime_adaptation.py").read_text()
    assert 'registry_path = Path(binding["official_registry_path"])' not in text
    assert "F5_RFF_NATIVE_EVIDENCE_ROOT" in text
    assert "synthetic_registry" in text


def test_runtime_helper_has_no_installer_or_numeric_invocation():
    tree = ast.parse((ROUTE / "src/rff_native_runtime.py").read_text())
    prohibited = {"fit", "fit_transform", "minimize", "average_precision_score", "system", "Popen", "run", "check_call"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # platform.system is an identity read, not os.system.
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "platform": continue
            assert node.func.attr not in prohibited
