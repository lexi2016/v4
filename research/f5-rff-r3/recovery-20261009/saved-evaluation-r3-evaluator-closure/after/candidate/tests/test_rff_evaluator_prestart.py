"""R3 _run_real pre-start integration; no real Mac, registry, or data access.

Original manifest-authenticated evaluator code and JSON run in a temporary
package through the real worker preflight and source loader. Peripheral seams:
load_documents, release/native validation, and the reviewed wrapper's absolute
Mac path attributes. An observation barrier stops before the first official
helper is loaded: no adapter, guard, registry, owner, or monitor is constructed.
"""
from __future__ import annotations

import builtins
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import test_rff_evaluator_dependencies as fixture_module

SRC = Path(__file__).resolve().parents[1] / "src"
OMITTED_DEPENDENCIES = (
    ("executable_helpers", "frozen_common"),
    ("executable_helpers", "frozen_features"),
    ("metadata_files", "frozen_base_features"),
    ("metadata_files", "frozen_contract"),
)


class StopBeforeOfficialRegistry(RuntimeError):
    """Observation barrier: the first official helper has not been loaded."""


class EvaluatorPrestartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.FrozenEvaluatorDependenciesTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.common = self.fixture.common
        self.root = self.fixture.root
        self.binding = self.fixture.binding
        frozen_helpers, frozen_metadata = self.common.bind_frozen_evaluator(self.fixture.metric_path)
        self.binding["executable_helpers"].update(frozen_helpers)
        self.binding["metadata_files"].update(frozen_metadata)
        self.fixture.wrapper_path_seam()
        self.runner = fixture_module.load_test_source(
            SRC / "run_rff_saved_evaluation.py", "r3_evaluator_prestart_runner")
        self.output = self.root / "execution/SYNTHETIC_R3_PREFLIGHT"
        self.trace = self.root / "evidence/resource.json"
        self.forbidden_paths = {self.root / "never_read" / name
                                for name in (*self.common.INPUT_NAMES, "candidate_model")}
        self.binding.update({
            "resources": {"cpu_threads": 4, "aggregate_process_tree_rss_bytes_max": 2147483648,
                          "wall_seconds_max": 60, "sample_seconds": .05},
            "output_root": str(self.output), "resource_trace_path": str(self.trace),
            "official_registry_path": str(self.root / "never_read/registry.jsonl"),
            "input_files": {name: {"path": str(self.root / "never_read" / name), "sha256": "0" * 64}
                            for name in self.common.INPUT_NAMES},
            "code_files": {name: self.common.file_record(SRC / (name + ".py"))
                           for name in self.common.SOURCE_NAMES},
            "official_helpers": {name: {"path": str(self.root / "never_read" / (name + ".py")),
                                         "sha256": "0" * 64}
                                 for name in ("execution_guard", "registry_adapter", "builder", "validator")},
        })
        self.forbidden_paths.add(Path(self.binding["official_registry_path"]))
        self.binding["code_sha256"] = self.common.sha256_bytes(self.common.canonical_bytes(self.binding["code_files"]))
        native_reference = self.root / "synthetic_native_reference.json"
        native_reference.write_text('{"synthetic_only": true}')
        self.binding["metadata_files"]["native_reference"] = self.common.file_record(native_reference)
        self.binding["executable_helpers"]["native_runtime"] = {
            "path": str(self.root / "SYNTHETIC_NATIVE_SEAM.py"), "sha256": "0" * 64}
        self.events = []
        self.read_attempts = []
        self.preflight_result = None
        self.owner = mock.Mock(side_effect=AssertionError("owner execution reached before observation barrier"))
        self.monitor = mock.Mock(side_effect=AssertionError("process monitor unexpectedly entered"))
        self.worker_alias = "_rff_saved_evaluator_preflight"
        old_worker = sys.modules.pop(self.worker_alias, None)
        self.addCleanup(self.restore_worker_alias, old_worker)

    def restore_worker_alias(self, previous):
        sys.modules.pop(self.worker_alias, None)
        if previous is not None:
            sys.modules[self.worker_alias] = previous

    def native_validation(self, spec, *, require_macos):
        self.assertTrue(require_macos)
        self.events.append("native_ready")
        return {"synthetic_native_runtime_seam": True}

    def run_to_observation_barrier(self):
        self.events.clear()
        self.read_attempts.clear()
        self.preflight_result = None
        original_loader = self.common.load_bound_module
        original_path_open, original_open = Path.open, builtins.open
        preflight_functions = []
        native = types.SimpleNamespace(
            native_spec_from_contract=lambda reference: {"synthetic_only": True},
            validate_native_files=self.native_validation)

        def record_read(path):
            if isinstance(path, (str, bytes, Path)):
                candidate = Path(path if not isinstance(path, bytes) else path.decode()).absolute()
                if candidate in self.forbidden_paths:
                    self.read_attempts.append(str(candidate))
                    raise AssertionError("preflight attempted a data, model, or registry read")

        def guarded_path_open(path, *args, **kwargs):
            record_read(path)
            return original_path_open(path, *args, **kwargs)

        def guarded_open(path, *args, **kwargs):
            record_read(path)
            return original_open(path, *args, **kwargs)

        def observed_loader(record, name, **kwargs):
            if name == "_rff_saved_native_runtime":
                return native
            if name in ("execution_guard_core", "_rff_saved_registry_adapter", "_rff_saved_registration"):
                self.events.append("official_boundary")
                raise StopBeforeOfficialRegistry(name)
            module = original_loader(record, name, **kwargs)
            if name == self.worker_alias:
                self.events.append("bound_worker_loaded")
                actual_preflight = module.preflight_evaluators
                preflight_functions.append((module, actual_preflight))
                def observed_preflight(common, binding):
                    self.events.append("evaluator_begin")
                    self.preflight_result = actual_preflight(common, binding)
                    self.events.append("evaluator_ready")
                    return self.preflight_result
                module.preflight_evaluators = observed_preflight
            return module

        try:
            with mock.patch.object(self.runner, "_common", return_value=self.common), \
                 mock.patch.object(self.common, "load_documents", return_value=({}, self.binding, b"{}", b"{}")), \
                 mock.patch.object(self.common, "verify_review_release", return_value={}), \
                 mock.patch.object(self.common, "load_bound_module", side_effect=observed_loader), \
                 mock.patch.object(self.runner, "_execute_bound", self.owner), \
                 mock.patch.object(self.runner, "_monitor_once", self.monitor), \
                 mock.patch.object(Path, "open", guarded_path_open), \
                 mock.patch.object(builtins, "open", guarded_open):
                self.runner._run_real(self.root / "SYNTHETIC_RUN_SPEC.json", self.root / "SYNTHETIC_BINDING.json")
        finally:
            for module, preflight in reversed(preflight_functions):
                module.preflight_evaluators = preflight

    def assert_no_execution_side_effects(self):
        self.owner.assert_not_called()
        self.monitor.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.trace.parent.exists())
        self.assertEqual(self.read_attempts, [])

    def assert_rejected_before_official_helper(self):
        with self.assertRaises(self.common.SavedEvaluationError):
            self.run_to_observation_barrier()
        self.assertNotIn("official_boundary", self.events)
        self.assertNotIn("evaluator_ready", self.events)
        self.assert_no_execution_side_effects()

    def test_real_preflight_completes_after_native_and_before_any_official_helper(self):
        with self.assertRaises(StopBeforeOfficialRegistry):
            self.run_to_observation_barrier()
        self.assertEqual(self.events, ["native_ready", "bound_worker_loaded", "evaluator_begin",
                                       "evaluator_ready", "official_boundary"])
        self.assertTrue(self.preflight_result["status"])
        self.assertRegex(self.preflight_result["closure_sha256"], r"^[a-f0-9]{64}$")
        for key, (name, _) in fixture_module.MODULE_FILES.items():
            self.assertEqual(sys.modules[name].__rff_source_sha256__,
                             self.binding["executable_helpers"][key]["sha256"])
        self.assert_no_execution_side_effects()

    def test_each_missing_dependency_rejects_before_start(self):
        for category, key in OMITTED_DEPENDENCIES:
            with self.subTest(dependency=key):
                original = self.binding[category].pop(key)
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    self.binding[category][key] = original

    def test_each_wrong_dependency_sha_rejects_before_start(self):
        for category, key in OMITTED_DEPENDENCIES:
            with self.subTest(dependency=key):
                original = self.binding[category][key]["sha256"]
                self.binding[category][key]["sha256"] = "0" * 64
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    self.binding[category][key]["sha256"] = original

    def test_each_missing_dependency_file_rejects_before_start(self):
        for category, key in OMITTED_DEPENDENCIES:
            with self.subTest(dependency=key):
                path = Path(self.binding[category][key]["path"])
                original = path.read_bytes()
                path.unlink()
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    path.write_bytes(original)

    def test_same_bytes_at_foreign_dependency_path_reject_before_start(self):
        for category, key in OMITTED_DEPENDENCIES:
            with self.subTest(dependency=key):
                original = self.binding[category][key]
                foreign = self.root / ("foreign_" + key)
                foreign.write_bytes(Path(original["path"]).read_bytes())
                self.binding[category][key] = self.common.file_record(foreign)
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    self.binding[category][key] = original

    def test_dependency_byte_drift_rejects_before_start(self):
        for category, key in OMITTED_DEPENDENCIES:
            with self.subTest(dependency=key):
                path = Path(self.binding[category][key]["path"])
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    path.write_bytes(original)

    def test_wrong_cached_module_file_or_spec_origin_rejects_before_start(self):
        for field in ("__file__", "__spec__.origin"):
            with self.subTest(field=field):
                record = self.binding["executable_helpers"]["frozen_common"]
                module = types.ModuleType("spike5.common")
                module.__file__ = record["path"]
                module.__spec__ = importlib.util.spec_from_file_location("spike5.common", record["path"])
                module.__rff_source_sha256__ = record["sha256"]
                module.__rff_evaluator_closure_sha256__ = self.common.validate_frozen_evaluator(self.binding)["closure_sha256"]
                if field == "__file__":
                    module.__file__ = str(self.root / "foreign_common.py")
                else:
                    module.__spec__.origin = str(self.root / "foreign_common.py")
                sys.modules["spike5.common"] = module
                try:
                    self.assert_rejected_before_official_helper()
                finally:
                    sys.modules.pop("spike5.common", None)

    def test_unknown_cached_package_module_rejects_before_start(self):
        module = types.ModuleType("spike5.extra")
        module.__file__ = str(self.root / "unbound_extra.py")
        sys.modules["spike5.extra"] = module
        self.assert_rejected_before_official_helper()

    def test_wrong_bound_worker_sha_rejects_before_start(self):
        self.binding["code_files"]["rff_saved_eval_worker"]["sha256"] = "0" * 64
        self.assert_rejected_before_official_helper()


if __name__ == "__main__":
    unittest.main()
