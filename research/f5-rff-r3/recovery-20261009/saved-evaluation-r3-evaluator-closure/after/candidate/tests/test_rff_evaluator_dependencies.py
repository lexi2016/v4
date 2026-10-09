"""R3 evaluator closure regressions; original source/config, synthetic placement.

All seven evaluator source/config files are copied byte-for-byte from the
historical MAC_FIXED_SOURCE_MANIFEST-authenticated recovery. No historical SHA,
PINS mapping, evaluator source, settings, or metric is replaced. The only loader
seam changes the already SHA-verified score-aware wrapper's two absolute path
attributes to this test's temporary package directory. The package __init__ is
the independently hash-authenticated 22-byte recovery, not a claimed Mac read.

Tests import code and configuration only. They never open data/model/registry
artifacts, call a metric, fit or predict, or run accepted PR5/R2 acceptance.
Unknown-module fault injection edits only a temporary copy and deliberately
updates its local record; the historical manifest must still reject that copy.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "candidate/src"
FIXTURE = Path(__file__).resolve().parent / "fixtures/frozen_evaluator"
ATTACHMENTS = ROOT / "inputs/attachments"
MANIFEST_SHA256 = "64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b"
MODULE_FILES = {
    "frozen_package_init": ("spike5", "spike5/__init__.py"),
    "frozen_common": ("spike5.common", "spike5/common.py"),
    "frozen_features": ("spike5.features", "spike5/features.py"),
    "frozen_settings": ("spike5.settings", "spike5/settings.py"),
    "frozen_metrics": ("spike5.metrics", "spike5/metrics.py"),
}
CONFIG_FILES = {
    "frozen_base_features": "config/base_features.json",
    "frozen_contract": "config/contract.json",
}


def load_test_source(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_historical_package(destination):
    """Reusable fixture adapter; source bytes and formal hashes stay intact."""
    destination = Path(destination)
    manifest_raw = (FIXTURE / "MAC_FIXED_SOURCE_MANIFEST.json").read_bytes()
    if len(manifest_raw) != 19131 or hashlib.sha256(manifest_raw).hexdigest() != MANIFEST_SHA256:
        raise AssertionError("historical evaluator fixture manifest identity mismatch")
    manifest = json.loads(manifest_raw)
    records = {item["path"]: item for item in manifest["files"]}
    for relative in [item[1] for item in MODULE_FILES.values()] + list(CONFIG_FILES.values()):
        raw = (FIXTURE / relative).read_bytes()
        expected = records[relative]
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise AssertionError(f"historical evaluator fixture identity mismatch: {relative}")
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return destination / "spike5/metrics.py"


class FrozenEvaluatorDependenciesTest(unittest.TestCase):
    def setUp(self):
        self.common = load_test_source(SRC / "rff_saved_eval_contracts.py", "rff_dependency_contracts")
        self.worker = load_test_source(SRC / "rff_saved_eval_worker.py", "rff_dependency_worker")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.metric_path = copy_historical_package(self.root / "historical package")
        self.package_root = self.metric_path.parent.parent
        self.original_pins = self.common.PINS
        self.original_pin_values = copy.deepcopy(self.common.PINS)
        self.addCleanup(self.assert_pins_unchanged)
        # Restore only the module namespace and sys.path that this loader owns.
        names = {name for name in sys.modules if name == "spike5" or name.startswith("spike5.")}
        names |= {"_rff_saved_score_aware", "_rff_saved_accepted_pr5", "_rff_saved_frames"}
        self.previous_modules = {name: sys.modules.pop(name) for name in names if name in sys.modules}
        self.previous_path = list(sys.path)
        self.previous_bytecode = sys.dont_write_bytecode
        self.addCleanup(self.restore_import_state)
        self.binding = self.manual_binding()

    def assert_pins_unchanged(self):
        self.assertIs(self.common.PINS, self.original_pins)
        self.assertEqual(self.common.PINS, self.original_pin_values)

    def restore_import_state(self):
        for name in list(sys.modules):
            if name == "spike5" or name.startswith("spike5.") or name in {
                "_rff_saved_score_aware", "_rff_saved_accepted_pr5", "_rff_saved_frames"}:
                sys.modules.pop(name, None)
        sys.modules.update(self.previous_modules)
        sys.path[:] = self.previous_path
        sys.dont_write_bytecode = self.previous_bytecode

    def manual_binding(self):
        helpers = {key: self.common.file_record(self.package_root / relative)
                   for key, (_, relative) in MODULE_FILES.items()}
        helpers.update({
            "accepted_worker": self.common.file_record(ATTACHMENTS / "rff/pr5_accepted/src/rff_worker.py"),
            "score_aware_metrics": self.common.file_record(ATTACHMENTS / "shared/src/score_aware_metrics.py"),
        })
        manifest = SRC.parent / "contracts/FROZEN_EVALUATOR_SOURCE_MANIFEST.json"
        # Before R3 the package copy does not exist. Use the identical historical
        # fixture solely so RED can reach the original loader's missing closure.
        if not manifest.is_file():
            manifest = FIXTURE / "MAC_FIXED_SOURCE_MANIFEST.json"
        metadata = {key: self.common.file_record(self.package_root / relative)
                    for key, relative in CONFIG_FILES.items()}
        metadata["frozen_evaluator_manifest"] = self.common.file_record(manifest, MANIFEST_SHA256)
        return {"executable_helpers": helpers, "metadata_files": metadata,
                "code_files": {"rff_saved_eval_frames": self.common.file_record(SRC / "rff_saved_eval_frames.py")}}

    def wrapper_path_seam(self):
        wrapper = self.common.load_bound_module(
            self.binding["executable_helpers"]["score_aware_metrics"], "_rff_saved_score_aware")
        self.assertEqual(wrapper.__rff_source_sha256__, self.common.PINS["score_aware_metrics"])
        wrapper.frozen_metrics.cache_clear()
        for field, value in (("FROZEN_METRICS_PATH", self.metric_path),
                             ("F5_SOURCE_ROOT", self.package_root)):
            patch = mock.patch.object(wrapper, field, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(wrapper.frozen_metrics.cache_clear)
        return wrapper

    def validate(self, binding=None):
        self.assertTrue(callable(getattr(self.common, "validate_frozen_evaluator", None)),
                        "R3 static frozen evaluator closure validator is missing")
        return self.common.validate_frozen_evaluator(self.binding if binding is None else binding)

    def test_original_transitive_loader_preserves_full_source_provenance(self):
        self.wrapper_path_seam()
        _, wrapper, accepted = self.worker._load_evaluators(self.common, self.binding)
        self.assertEqual(accepted.__rff_source_sha256__, self.common.PINS["accepted_worker"])
        self.assertIs(wrapper.frozen_metrics(), sys.modules["spike5.metrics"])
        for key, (name, _) in MODULE_FILES.items():
            with self.subTest(module=name):
                record = self.binding["executable_helpers"][key]
                module = sys.modules[name]
                self.assertEqual(Path(module.__file__).resolve(), Path(record["path"]))
                self.assertEqual(Path(module.__spec__.origin).resolve(), Path(record["path"]))
                self.assertEqual(module.__rff_source_sha256__, record["sha256"])
        settings = sys.modules["spike5.settings"]
        original = json.loads((FIXTURE / "config/contract.json").read_bytes())
        self.assertEqual(settings.CONTRACT, original)
        self.assertEqual(settings.PARAMS, original["learner"]["params"])
        self.assertEqual(settings.ROUNDS, original["learner"]["rounds"])
        self.assertEqual(settings.BASE_FEATURES, json.loads((FIXTURE / "config/base_features.json").read_bytes()))
        self.assertEqual(settings.FEATURES, settings.BASE_FEATURES + sys.modules["spike5.features"].PATH_FEATURES)
        self.assertEqual(settings.CONTRACT["calibration_bins"], [0, .001, .003, .01, .03, .1, .3, .6, 1])
        read_json = sys.modules["spike5.common"].read_json
        self.assertEqual(read_json.__module__, "spike5.common")
        self.assertEqual(Path(read_json.__code__.co_filename).resolve(),
                         Path(self.binding["executable_helpers"]["frozen_common"]["path"]))

    def test_bind_api_uses_complete_historical_manifest_without_import(self):
        self.assertTrue(callable(getattr(self.common, "bind_frozen_evaluator", None)),
                        "R3 historical evaluator binding function is missing")
        with mock.patch.object(self.common, "load_bound_module", side_effect=AssertionError("static bind imported code")):
            helpers, metadata = self.common.bind_frozen_evaluator(self.metric_path)
        self.assertEqual(set(helpers), set(MODULE_FILES))
        self.assertEqual(set(metadata), {*CONFIG_FILES, "frozen_evaluator_manifest"})
        self.assertEqual(metadata["frozen_evaluator_manifest"]["sha256"], MANIFEST_SHA256)
        for key in MODULE_FILES:
            self.assertEqual(helpers[key], self.binding["executable_helpers"][key])
        for key in CONFIG_FILES:
            self.assertEqual(metadata[key], self.binding["metadata_files"][key])
        self.assertFalse(any(name == "spike5" or name.startswith("spike5.") for name in sys.modules))

    def test_static_validation_returns_exact_module_and_config_closure(self):
        with mock.patch.object(self.common, "load_bound_module", side_effect=AssertionError("static validate imported code")):
            result = self.validate()
        self.assertEqual(result["modules"], {name: self.binding["executable_helpers"][key]
                                            for key, (name, _) in MODULE_FILES.items()})
        self.assertEqual(result["configs"], {record["path"]: record for key, record in
                         self.binding["metadata_files"].items() if key in CONFIG_FILES})
        self.assertRegex(result["closure_sha256"], r"^[a-f0-9]{64}$")
        self.assertFalse(any(name == "spike5" or name.startswith("spike5.") for name in sys.modules))

    def test_each_previously_omitted_dependency_is_required(self):
        for category, key in (("executable_helpers", "frozen_common"),
                              ("executable_helpers", "frozen_features"),
                              ("metadata_files", "frozen_base_features"),
                              ("metadata_files", "frozen_contract")):
            with self.subTest(dependency=key):
                binding = copy.deepcopy(self.binding)
                del binding[category][key]
                with self.assertRaises(self.common.SavedEvaluationError):
                    self.validate(binding)

    def test_each_source_and_configuration_hash_is_historically_fixed(self):
        for category, keys in (("executable_helpers", MODULE_FILES), ("metadata_files", CONFIG_FILES)):
            for key in keys:
                with self.subTest(dependency=key):
                    binding = copy.deepcopy(self.binding)
                    binding[category][key]["sha256"] = "0" * 64
                    with self.assertRaises(self.common.SavedEvaluationError):
                        self.validate(binding)

    def test_manifest_identity_cannot_be_rebound_to_another_self_consistent_file(self):
        binding = copy.deepcopy(self.binding)
        path = self.root / "altered_manifest.json"
        document = json.loads((FIXTURE / "MAC_FIXED_SOURCE_MANIFEST.json").read_bytes())
        document["identity_kind"] = "SYNTHETIC_NOT_HISTORICAL"
        path.write_text(json.dumps(document))
        binding["metadata_files"]["frozen_evaluator_manifest"] = self.common.file_record(path)
        with self.assertRaises(self.common.SavedEvaluationError):
            self.validate(binding)

    def test_declared_byte_counts_cannot_disagree_with_historical_identities(self):
        for category, key in (("executable_helpers", "frozen_common"),
                              ("metadata_files", "frozen_contract")):
            with self.subTest(dependency=key):
                binding = copy.deepcopy(self.binding)
                binding[category][key]["bytes"] += 1
                with self.assertRaises(self.common.SavedEvaluationError):
                    self.validate(binding)

    def test_identical_bytes_in_foreign_package_cannot_rebind_a_dependency(self):
        for category, key in (("executable_helpers", "frozen_common"),
                              ("executable_helpers", "frozen_features"),
                              ("metadata_files", "frozen_base_features"),
                              ("metadata_files", "frozen_contract")):
            with self.subTest(dependency=key):
                binding = copy.deepcopy(self.binding)
                original = Path(binding[category][key]["path"])
                destination = self.root / "foreign" / key / original.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original.read_bytes())
                binding[category][key] = self.common.file_record(destination)
                with self.assertRaises(self.common.SavedEvaluationError):
                    self.validate(binding)

    def test_unknown_module_is_rejected_before_its_body_executes(self):
        self.wrapper_path_seam()
        marker = self.root / "unbound_body_executed"
        (self.metric_path.parent / "extra.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
        init = self.metric_path.parent / "__init__.py"
        init.write_text("from . import extra\n")
        self.binding["executable_helpers"]["frozen_package_init"] = self.common.file_record(init)
        with self.assertRaises(self.common.SavedEvaluationError):
            self.worker._load_evaluators(self.common, self.binding)
        self.assertFalse(marker.exists(), "unbound body ran before the loader rejected its origin")
        self.assertNotIn("spike5.extra", sys.modules)

    def test_unbound_cached_package_is_rejected_before_any_package_body(self):
        self.wrapper_path_seam()
        extra = types.ModuleType("spike5.extra")
        extra.__file__ = str(self.root / "unbound_cached.py")
        sys.modules["spike5.extra"] = extra
        calls = []
        original = self.common.load_bound_module
        def observed(record, name, **kwargs):
            calls.append(name)
            return original(record, name, **kwargs)
        with mock.patch.object(self.common, "load_bound_module", side_effect=observed):
            with self.assertRaises(self.common.SavedEvaluationError):
                self.worker._load_evaluators(self.common, self.binding)
        self.assertFalse(any(name == "spike5" or name.startswith("spike5.") for name in calls))

    def test_config_drift_cannot_reuse_a_previously_loaded_settings_cache(self):
        self.wrapper_path_seam()
        self.worker._load_evaluators(self.common, self.binding)
        original_settings = sys.modules["spike5.settings"]
        path = Path(self.binding["metadata_files"]["frozen_contract"]["path"])
        changed = json.loads(path.read_bytes())
        changed["calibration_bins"] = [0, 1]
        path.write_text(json.dumps(changed))
        self.binding["metadata_files"]["frozen_contract"] = self.common.file_record(path)
        with self.assertRaises(self.common.SavedEvaluationError):
            self.worker._load_evaluators(self.common, self.binding)
        self.assertIs(sys.modules["spike5.settings"], original_settings)
        self.assertNotEqual(original_settings.CONTRACT["calibration_bins"], [0, 1])

    def test_closure_fingerprint_is_required_on_cached_package_modules(self):
        self.wrapper_path_seam()
        self.worker._load_evaluators(self.common, self.binding)
        settings = sys.modules["spike5.settings"]
        self.assertRegex(getattr(settings, "__rff_evaluator_closure_sha256__", ""), r"^[a-f0-9]{64}$")
        settings.__rff_evaluator_closure_sha256__ = "0" * 64
        with self.assertRaises(self.common.SavedEvaluationError):
            self.worker._load_evaluators(self.common, self.binding)

    def test_cached_spec_origin_cannot_disagree_with_verified_file_origin(self):
        self.wrapper_path_seam()
        self.worker._load_evaluators(self.common, self.binding)
        settings = sys.modules["spike5.settings"]
        settings.__spec__.origin = str(self.root / "foreign_settings.py")
        with self.assertRaises(self.common.SavedEvaluationError):
            self.worker._load_evaluators(self.common, self.binding)

    def test_preflight_loads_code_and_configuration_without_metric_or_data_calls(self):
        self.wrapper_path_seam()
        self.assertTrue(callable(getattr(self.worker, "preflight_evaluators", None)),
                        "R3 source/config-only evaluator preflight is missing")
        forbidden = self.root / "must_not_read_data"
        binding = copy.deepcopy(self.binding)
        binding["input_files"] = {"eval_truth": {"path": str(forbidden), "sha256": "0" * 64}}
        # Observe actual Python calls without substituting any frozen function.
        # Import-time <module> execution is expected; evaluator function calls
        # would cross the source/config-only preflight boundary.
        metric_calls = []
        previous_profile = sys.getprofile()
        def observe_calls(frame, event, arg):
            if event == "call" and frame.f_code.co_filename == str(self.metric_path) and frame.f_code.co_name != "<module>":
                metric_calls.append(frame.f_code.co_name)
        try:
            sys.setprofile(observe_calls)
            with mock.patch.object(self.worker, "_read_csv", side_effect=AssertionError("preflight decoded data")):
                result = self.worker.preflight_evaluators(self.common, binding)
        finally:
            sys.setprofile(previous_profile)
        self.assertTrue(result["status"])
        self.assertRegex(result["closure_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(metric_calls, [])
        self.assertFalse(forbidden.exists())
        self.assertIn("spike5.settings", sys.modules)


if __name__ == "__main__":
    unittest.main()
