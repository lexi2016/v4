"""Saved-file worker tests with synthetic CSVs and machine-only metric import substitution.

The worker I/O, frozen frame composition, accepted join and all counters run.
The real Mac spike5.settings path and native runtime are unavailable. Normal
worker cases substitute only evaluator loading and the child-native verification
seam with explicit synthetic fixtures; neither is a production skip branch.
Focused loader cases exercise bound source loading on source-only temporary
files. They do not claim acceptance of the real Mac runtime or settings.
"""
from __future__ import annotations
import copy
import gzip
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import rff_saved_eval_contracts as common
import test_rff_saved_eval_frames as fixture_module


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class SavedWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.SavedFramesTests.setUpClass()
        cls.frame_fixture = fixture_module.SavedFramesTests()
        cls.frame_module = load(SRC / "rff_saved_eval_frames.py", "rff_worker_test_frames")

    @classmethod
    def tearDownClass(cls):
        fixture_module.SavedFramesTests.tearDownClass()

    def setUp(self):
        path = SRC / "rff_saved_eval_worker.py"
        self.assertTrue(path.is_file(), "RFF saved-file worker is missing")
        self.worker = load(path, "rff_worker_under_test")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.frames = self.frame_fixture.make_frames()
        self.inputs = {}
        all_frames = {"candidate_scores": self.frames["candidate_scores"],
            "candidate_top3": self.frames["candidate_top3"], "eval_truth": self.frames["truth"],
            "eval_calendar": self.frames["calendar"]}
        for arm, value in self.frames["controls"].items():
            for kind in ("scores", "top3"):
                all_frames[f"{arm}_{kind}"] = value[kind]
        for name, frame in all_frames.items():
            path = self.root / (name + ".csv.gz")
            path.write_bytes(gzip.compress(frame.to_csv(index=False).encode(), mtime=0))
            self.inputs[name] = common.file_record(path)
        output = self.root / "execution" / "SYNTHETIC_SAVED_EVAL"
        output.mkdir(parents=True)
        self.output = output
        contract_path = self.root / "experiment.json"
        common.write_json_exclusive(contract_path, self.frames["experiment_contract"])
        ev = self.frames["evaluation_contract"]
        seal = {"schema": "F5_FULL64_RFF_PREDICTION_SEAL_V1", "route_id": common.ROUTE,
            "execution_id": common.CANDIDATE,
            "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
            "score_kind": "RAW_LOGISTIC_DECISION_MARGIN", "probability_kind": "FITTED_LOGISTIC_SIGMOID_NO_CALIBRATOR",
            "grid_rows": ev["grid_rows"], "scoreable_rows": ev["scoreable_rows"],
            "evaluation_sessions": ev["sessions"], "predict_calls": 1,
            "evaluation_label_values_decoded": False, "safety": common.SAFETY,
            "candidate_scores_sha256": self.inputs["candidate_scores"]["sha256"],
            "candidate_top3_sha256": self.inputs["candidate_top3"]["sha256"]}
        seal_path = self.root / "seal.json"
        common.write_json_exclusive(seal_path, seal)
        code = {p.stem: common.file_record(p) for p in SRC.glob("*.py")}
        self.binding = {"execution_id": output.name, "candidate_execution_id": common.CANDIDATE,
            "route_id": common.ROUTE, "output_root": str(output),
            "input_files": self.inputs, "code_files": code,
            "code_sha256": common.sha256_bytes(common.canonical_bytes(code)),
            "executable_helpers": {}, "official_helpers": {},
            "metadata_files": {"experiment_contract": common.file_record(contract_path),
                               "prediction_seal": common.file_record(seal_path)},
            "evaluation_contract": ev, "synthetic_only": True,
            "start_receipt_path": str(output / "EVALUATION_START_RECEIPT.json"),
            "input_binding_path": str(self.root / "binding.json"),
            "run_spec_path": str(self.root / "spec.json")}
        spec = {**{key: 0 for key in common.ZERO_AUTHORIZATIONS},
            "candidate_model_load_authorized": False, "evaluation_truth_decode_authorized": 1,
            "execution_id": output.name, "candidate_execution_id": common.CANDIDATE,
            "route_id": common.ROUTE, "automatic_retry": False, "safety": common.SAFETY}
        self.binding["run_spec_sha256"] = common.write_json_exclusive(Path(self.binding["run_spec_path"]), spec)
        binding_sha = common.write_json_exclusive(Path(self.binding["input_binding_path"]), self.binding)
        start = {"status": "RUN_STARTED_DURABLE", "execution_id": output.name, "candidate_execution_id": common.CANDIDATE,
            "route_id": common.ROUTE, "run_spec_sha256": self.binding["run_spec_sha256"],
            "input_binding_sha256": binding_sha, "source_code_sha256": self.binding["code_sha256"],
            "start_event_sha256": "f" * 64, "real_fit_budget_debit": 0,
            "planned_real_fit_count": 0, "official_registry_sha256_after_start": "e" * 64,
            **common.ZERO_COUNTS}
        start_sha = common.write_json_exclusive(Path(self.binding["start_receipt_path"]), start)
        self.payload = {**self.binding, "input_binding_sha256": binding_sha,
                        "start_receipt_sha256": start_sha}
        deps = (self.frame_module, self.frame_fixture.score_aware, self.frame_fixture.accepted)
        self.import_patch = mock.patch.object(self.worker, "_load_evaluators", return_value=deps)
        self.import_patch.start()
        self.addCleanup(self.import_patch.stop)
        self.native_observation = {"synthetic_only": True,
            "scope": "SYNTHETIC_CHILD_NATIVE_VERIFICATION_SUBSTITUTION",
            "dependency_distribution_lock_verified": False}
        self.native_patch = mock.patch.object(self.worker, "_validate_child_runtime",
            return_value=self.native_observation, create=True)
        self.native_mock = self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def status(self):
        return json.loads((self.output / "EVALUATION_WORKER_STATUS.json").read_bytes())

    def run_success(self):
        self.worker.run_saved_evaluation(self.payload)
        return self.status()

    def restore_module_later(self, name):
        previous = sys.modules.pop(name, None)
        def restore():
            sys.modules.pop(name, None)
            if previous is not None:
                sys.modules[name] = previous
        self.addCleanup(restore)

    def loader_binding(self):
        """Exact accepted source; only the absent Mac package path is substituted."""
        for name in ("_rff_saved_accepted_pr5", "_rff_saved_score_aware", "_rff_saved_frames",
                     "spike5", "spike5.settings", "spike5.metrics", "spike5.extra"):
            self.restore_module_later(name)
        package = self.root / "synthetic_frozen" / "spike5"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("# Synthetic package init; no real settings claim.\n")
        (package / "settings.py").write_text("CONTRACT = {'calibration_bins': [0.0, 0.5, 1.0]}\n")
        (package / "metrics.py").write_bytes((fixture_module.REMOTE / "external_frozen_evaluator/metrics.py").read_bytes())
        helpers = {
            "accepted_worker": common.file_record(fixture_module.ATTACHMENTS / "rff/pr5_accepted/src/rff_worker.py"),
            "score_aware_metrics": common.file_record(fixture_module.ATTACHMENTS / "shared/src/score_aware_metrics.py"),
            "frozen_metrics": common.file_record(package / "metrics.py"),
            "frozen_settings": common.file_record(package / "settings.py"),
            "frozen_package_init": common.file_record(package / "__init__.py"),
        }
        wrapper = common.load_bound_module(helpers["score_aware_metrics"], "_rff_saved_score_aware")
        wrapper.frozen_metrics.cache_clear()
        for field, value in (("FROZEN_METRICS_PATH", package / "metrics.py"), ("F5_SOURCE_ROOT", package.parent)):
            patch = mock.patch.object(wrapper, field, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(wrapper.frozen_metrics.cache_clear)
        def remove_fixture_path():
            if str(package.parent) in sys.path:
                sys.path.remove(str(package.parent))
        self.addCleanup(remove_fixture_path)
        return {"executable_helpers": helpers, "code_files": self.binding["code_files"]}

    def native_binding(self):
        """Synthetic source fixture for the native API seam, not an ABI check."""
        self.restore_module_later("_rff_saved_native_runtime")
        source = self.root / "synthetic_native_runtime.py"
        source.write_text(
            "def native_spec_from_contract(contract):\n"
            "    return dict(contract['synthetic_native_spec'])\n"
            "def verify_child_launch_environment(spec):\n"
            "    return {'synthetic_only': True, 'observed_spec': dict(spec), "
            "'dependency_distribution_lock_verified': False}\n")
        spec = {"python_executable_path": "SYNTHETIC_PYTHON_IDENTITY", "dyld_library_path": ""}
        reference = self.root / "synthetic_native_reference.json"
        common.write_json_exclusive(reference, {"synthetic_only": True, "synthetic_native_spec": spec})
        return {"executable_helpers": {"native_runtime": common.file_record(source)},
                "metadata_files": {"native_reference": common.file_record(reference)}}, spec

    def test_synthetic_saved_files_complete_without_fit_predict_or_model(self):
        before = {k: common.sha256_file(Path(v["path"])) for k, v in self.inputs.items()}
        with mock.patch.object(self.frame_fixture.accepted, "run_candidate_worker", side_effect=AssertionError("candidate entry called")):
            status = self.run_success()
        self.assertEqual(status["status"], "COMPLETED")
        for key, value in common.ZERO_COUNTS.items():
            self.assertEqual(status[key], value)
        self.assertEqual(status["evaluation_truth_decode_attempts"], 1)
        self.assertEqual(status["evaluation_truth_decodes_completed"], 1)
        self.assertEqual(status["control_label_artifacts_decoded"], 2)
        self.assertEqual(before, {k: common.sha256_file(Path(v["path"])) for k, v in self.inputs.items()})
        result = json.loads((self.output / "EVALUATION_RESULT_RECEIPT.json").read_bytes())
        self.assertEqual(result["metrics_sha256"], common.sha256_file(self.output / "METRICS.json"))
        marker = json.loads((self.output / "EVALUATION_TRUTH_READ_START.json").read_bytes())
        self.assertEqual(marker["evaluation_truth_decode_attempts"], 1)
        self.assertEqual(marker["fit_calls"], 0)

    def test_score_hash_drift_stops_before_truth_decode(self):
        Path(self.inputs["candidate_scores"]["path"]).write_bytes(b"drift")
        with self.assertRaisesRegex(Exception, "SHA_MISMATCH"):
            self.worker.run_saved_evaluation(self.payload)
        self.assertEqual(self.status()["evaluation_truth_decode_attempts"], 0)
        self.assertFalse((self.output / "EVALUATION_TRUTH_READ_START.json").exists())

    def test_truth_parser_failure_preserves_attempt_one_completion_zero(self):
        original = self.worker._read_csv
        def broken(raw, *, name, columns):
            if name == "eval_truth":
                raise ValueError("SYNTHETIC_TRUTH_PARSE_FAILURE")
            return original(raw, name=name, columns=columns)
        with mock.patch.object(self.worker, "_read_csv", side_effect=broken):
            with self.assertRaisesRegex(Exception, "SYNTHETIC_TRUTH_PARSE_FAILURE"):
                self.worker.run_saved_evaluation(self.payload)
        status = self.status()
        self.assertEqual(status["evaluation_truth_decode_attempts"], 1)
        self.assertEqual(status["evaluation_truth_decodes_completed"], 0)
        self.assertFalse(status["evaluation_label_values_decoded"])
        self.assertTrue((self.output / "EVALUATION_TRUTH_READ_START.json").is_file())

    def test_score_parser_failure_does_not_open_truth_file(self):
        original = self.worker._read_csv
        def broken(raw, *, name, columns):
            if name == "candidate_scores":
                raise ValueError("SYNTHETIC_SCORE_PARSE_FAILURE")
            return original(raw, name=name, columns=columns)
        with mock.patch.object(self.worker, "_read_csv", side_effect=broken):
            with self.assertRaisesRegex(Exception, "SYNTHETIC_SCORE_PARSE_FAILURE"):
                self.worker.run_saved_evaluation(self.payload)
        self.assertEqual(self.status()["evaluation_truth_artifact_read_attempts"], 0)
        self.assertEqual(self.status()["evaluation_truth_decode_attempts"], 0)

    def test_reentry_never_replaces_existing_result_or_status(self):
        self.run_success()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaisesRegex(Exception, "REENTRY"):
            self.worker.run_saved_evaluation(self.payload)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_payload_cannot_swap_an_unbound_score_file(self):
        tampered = copy.deepcopy(self.payload)
        tampered["input_files"]["candidate_scores"] = tampered["input_files"]["candidate_top3"]
        with self.assertRaisesRegex(Exception, "PAYLOAD_BINDING"):
            self.worker.run_saved_evaluation(tampered)

    def test_success_receipts_bind_the_complete_identity_chain(self):
        status = self.run_success()
        result = json.loads((self.output / "EVALUATION_RESULT_RECEIPT.json").read_bytes())
        metrics = json.loads((self.output / "METRICS.json").read_bytes())
        marker = json.loads((self.output / "EVALUATION_TRUTH_READ_START.json").read_bytes())
        identity = {"execution_id": self.binding["execution_id"], "route_id": common.ROUTE,
            "candidate_execution_id": common.CANDIDATE, "run_spec_sha256": self.binding["run_spec_sha256"],
            "input_binding_sha256": self.payload["input_binding_sha256"],
            "start_receipt_sha256": self.payload["start_receipt_sha256"],
            "source_code_sha256": self.binding["code_sha256"]}
        for label, document in (("status", status), ("result", result), ("metrics", metrics), ("marker", marker)):
            for key, value in identity.items():
                with self.subTest(document=label, key=key):
                    self.assertEqual(document.get(key), value)
        for document in (status, result, metrics):
            self.assertIs(document.get("metrics_computed"), True)
        self.assertEqual(result["input_sha256"], {name: record["sha256"] for name, record in self.inputs.items()})
        self.assertEqual(result["evidence_ceiling"], "DIRECTION_ONLY")

    def test_start_must_be_durable_before_any_evaluation_input(self):
        start_path = Path(self.binding["start_receipt_path"])
        start = json.loads(start_path.read_bytes())
        start["status"] = "PREPARED"
        start_path.write_bytes(common.canonical_bytes(start))
        self.payload["start_receipt_sha256"] = common.sha256_file(start_path)
        with self.assertRaisesRegex(Exception, "WORKER_DURABLE_START_IDENTITY_MISMATCH:status"):
            self.worker.run_saved_evaluation(self.payload)
        self.native_mock.assert_not_called()
        self.assertEqual({p.name for p in self.output.iterdir()}, {start_path.name})

    def test_truth_snapshot_hash_failure_has_one_read_attempt_and_zero_decodes(self):
        truth_path = Path(self.inputs["eval_truth"]["path"])
        truth_path.write_bytes(b"SYNTHETIC_TRUTH_HASH_DRIFT")
        reads = []
        original = Path.read_bytes
        def observed_read(path):
            if path == truth_path:
                reads.append(path)
            return original(path)
        with mock.patch.object(Path, "read_bytes", new=observed_read):
            with self.assertRaisesRegex(Exception, "BOUND_SNAPSHOT_SHA_MISMATCH:eval_truth"):
                self.worker.run_saved_evaluation(self.payload)
        status = self.status()
        self.assertEqual(reads, [truth_path])
        self.assertEqual(status["evaluation_truth_artifact_read_attempts"], 1)
        self.assertEqual(status["evaluation_truth_artifact_reads_completed"], 0)
        self.assertEqual(status["evaluation_truth_decode_attempts"], 0)
        self.assertEqual(status["evaluation_truth_decodes_completed"], 0)
        self.assertEqual(status["control_label_artifacts_decoded"], 0)
        self.assertFalse(status["evaluation_label_values_decoded"])
        self.assertIs(status.get("metrics_computed"), False)
        self.assertFalse((self.output / "EVALUATION_TRUTH_READ_START.json").exists())

    def test_later_control_parse_failure_preserves_consumed_truth_and_first_control(self):
        original = self.worker._read_csv
        def broken(raw, *, name, columns):
            if name == common.CONTROLS[1] + "_scores":
                raise ValueError("SYNTHETIC_SECOND_CONTROL_PARSE_FAILURE")
            return original(raw, name=name, columns=columns)
        with mock.patch.object(self.worker, "_read_csv", side_effect=broken):
            with self.assertRaisesRegex(Exception, "SYNTHETIC_SECOND_CONTROL_PARSE_FAILURE"):
                self.worker.run_saved_evaluation(self.payload)
        status = self.status()
        evidence = json.loads((self.output / "EVALUATION_FAILURE_EVIDENCE.json").read_bytes())
        for document in (status, evidence):
            self.assertEqual(document["evaluation_truth_artifact_read_attempts"], 1)
            self.assertEqual(document["evaluation_truth_artifact_reads_completed"], 1)
            self.assertEqual(document["evaluation_truth_decode_attempts"], 1)
            self.assertEqual(document["evaluation_truth_decodes_completed"], 1)
            self.assertEqual(document["control_label_artifacts_decoded"], 1)
            self.assertTrue(document["evaluation_label_values_decoded"])
            self.assertIs(document.get("metrics_computed"), False)
            self.assertEqual(document.get("run_spec_sha256"), self.binding["run_spec_sha256"])
            self.assertEqual(document.get("source_code_sha256"), self.binding["code_sha256"])
        self.assertFalse((self.output / "METRICS.json").exists())
        self.assertFalse((self.output / "EVALUATION_RESULT_RECEIPT.json").exists())

    def test_result_write_failure_persists_computed_metrics_and_actual_counts(self):
        worker_common = self.worker._common(self.payload)
        original = worker_common.write_json_exclusive
        attempts = []
        def broken(path, value):
            if path.name == "EVALUATION_RESULT_RECEIPT.json":
                attempts.append(path.name)
                raise OSError("SYNTHETIC_RESULT_WRITE_FAILURE")
            return original(path, value)
        with mock.patch.object(worker_common, "write_json_exclusive", side_effect=broken):
            with self.assertRaisesRegex(Exception, "SYNTHETIC_RESULT_WRITE_FAILURE"):
                self.worker.run_saved_evaluation(self.payload)
        status = self.status()
        self.assertEqual(attempts, ["EVALUATION_RESULT_RECEIPT.json"])
        self.assertEqual(status["status"], "FAILED")
        self.assertIs(status.get("metrics_computed"), True)
        self.assertEqual(status.get("metrics_sha256"), common.sha256_file(self.output / "METRICS.json"))
        self.assertEqual(status["evaluation_truth_decodes_completed"], 1)
        self.assertEqual(status["control_label_artifacts_decoded"], 2)
        self.assertTrue((self.output / "EVALUATION_FAILURE_EVIDENCE.json").is_file())

    def test_child_native_check_is_observed_before_evaluator_loading(self):
        order = []
        deps = (self.frame_module, self.frame_fixture.score_aware, self.frame_fixture.accepted)
        self.native_mock.side_effect = lambda *args: (order.append("native") or self.native_observation)
        with mock.patch.object(self.worker, "_load_evaluators", side_effect=lambda *args: (order.append("evaluators") or deps)):
            status = self.run_success()
        self.assertEqual(order, ["native", "evaluators"])
        self.assertEqual(status.get("native_runtime_check_attempts"), 1)
        self.assertEqual(status.get("native_runtime_checks_completed"), 1)
        self.assertEqual(status.get("native_runtime_observation"), self.native_observation)

    def test_child_native_failure_is_durable_with_zero_truth_and_no_evaluator_load(self):
        self.native_mock.side_effect = ValueError("SYNTHETIC_NATIVE_IDENTITY_FAILURE")
        with mock.patch.object(self.worker, "_load_evaluators") as loader:
            with self.assertRaisesRegex(Exception, "SYNTHETIC_NATIVE_IDENTITY_FAILURE"):
                self.worker.run_saved_evaluation(self.payload)
        loader.assert_not_called()
        status = self.status()
        self.assertEqual(status.get("native_runtime_check_attempts"), 1)
        self.assertEqual(status.get("native_runtime_checks_completed"), 0)
        self.assertIsNone(status.get("native_runtime_observation"))
        self.assertEqual(status["evaluation_truth_artifact_read_attempts"], 0)
        self.assertEqual(status["evaluation_truth_decode_attempts"], 0)
        self.assertIs(status.get("metrics_computed"), False)
        self.assertTrue((self.output / "EVALUATION_FAILURE_EVIDENCE.json").is_file())

    def test_cached_common_module_requires_matching_origin_and_full_sha(self):
        record = self.payload["code_files"]["rff_saved_eval_contracts"]
        name = "_rff_saved_common_" + record["sha256"][:16]
        self.restore_module_later(name)
        imposter = types.ModuleType(name)
        imposter.__file__ = str(self.root / "unbound_common.py")
        imposter.__rff_source_sha256__ = record["sha256"]
        sys.modules[name] = imposter
        with self.assertRaisesRegex(Exception, "WORKER_COMMON_CACHED_SOURCE_IDENTITY_MISMATCH"):
            self.worker._common(self.payload)
        imposter.__file__ = record["path"]
        imposter.__rff_source_sha256__ = "0" * 64
        with self.assertRaisesRegex(Exception, "WORKER_COMMON_CACHED_SOURCE_IDENTITY_MISMATCH"):
            self.worker._common(self.payload)

    def test_new_common_module_records_the_full_verified_source_identity(self):
        record = self.payload["code_files"]["rff_saved_eval_contracts"]
        name = "_rff_saved_common_" + record["sha256"][:16]
        self.restore_module_later(name)
        loaded = self.worker._common(self.payload)
        self.assertEqual(getattr(loaded, "__rff_source_sha256__", None), record["sha256"])
        self.assertEqual(Path(loaded.__file__).resolve(), Path(record["path"]).resolve())

    def test_unaccepted_join_source_is_rejected_before_its_module_body_runs(self):
        source = self.root / "unaccepted_worker.py"
        source.write_text("raise AssertionError('SYNTHETIC_UNACCEPTED_SOURCE_EXECUTED')\n")
        binding = {"executable_helpers": {"accepted_worker": common.file_record(source)}}
        self.import_patch.stop()
        with self.assertRaisesRegex(Exception, "ACCEPTED_PR5_JOIN_SHA_MISMATCH"):
            self.worker._load_evaluators(common, binding)

    def test_bound_frozen_loader_preserves_exact_source_provenance(self):
        binding = self.loader_binding()
        self.import_patch.stop()
        frames, wrapper, accepted = self.worker._load_evaluators(common, binding)
        self.assertEqual(accepted.__rff_source_sha256__, common.PINS["accepted_worker"])
        self.assertEqual(wrapper.__rff_source_sha256__, common.PINS["score_aware_metrics"])
        self.assertIs(wrapper.frozen_metrics(), sys.modules["spike5.metrics"])
        self.assertEqual(frames.__rff_source_sha256__, binding["code_files"]["rff_saved_eval_frames"]["sha256"])

    def test_settings_and_init_must_share_the_frozen_metrics_physical_package(self):
        binding = self.loader_binding()
        self.import_patch.stop()
        original = binding["executable_helpers"]["frozen_settings"]
        outside = self.root / "foreign_package"
        outside.mkdir()
        settings = outside / "settings.py"
        settings.write_bytes(Path(original["path"]).read_bytes())
        binding["executable_helpers"]["frozen_settings"] = common.file_record(settings)
        with self.assertRaisesRegex(Exception, "FROZEN_EVALUATOR_PACKAGE_LOCATION_MISMATCH:frozen_settings"):
            self.worker._load_evaluators(common, binding)
        self.assertNotIn("spike5", sys.modules)

    def test_package_init_cannot_be_loaded_from_a_different_directory(self):
        binding = self.loader_binding()
        self.import_patch.stop()
        outside = self.root / "foreign_init"
        outside.mkdir()
        init = outside / "__init__.py"
        init.write_text("# Synthetic external init.\n")
        binding["executable_helpers"]["frozen_package_init"] = common.file_record(init)
        with self.assertRaisesRegex(Exception, "FROZEN_EVALUATOR_PACKAGE_LOCATION_MISMATCH:frozen_package_init"):
            self.worker._load_evaluators(common, binding)

    def test_unbound_frozen_package_import_is_rejected(self):
        binding = self.loader_binding()
        self.import_patch.stop()
        init = Path(binding["executable_helpers"]["frozen_package_init"]["path"])
        (init.parent / "extra.py").write_text("SYNTHETIC_EXTRA_MODULE = True\n")
        init.write_text("from . import extra\n")
        binding["executable_helpers"]["frozen_package_init"] = common.file_record(init)
        with self.assertRaisesRegex(Exception, "UNBOUND_FROZEN_PACKAGE_DEPENDENCY:spike5.extra"):
            self.worker._load_evaluators(common, binding)

    def test_child_runtime_seam_uses_bound_reference_and_preserves_observation(self):
        self.native_patch.stop()
        self.assertTrue(callable(getattr(self.worker, "_validate_child_runtime", None)), "Child runtime verification seam is missing")
        binding, spec = self.native_binding()
        observation = self.worker._validate_child_runtime(common, binding, {"native_spec": spec})
        self.assertEqual(observation, {"synthetic_only": True, "observed_spec": spec,
                                       "dependency_distribution_lock_verified": False})

    def test_child_runtime_spec_cannot_override_bound_native_reference(self):
        self.native_patch.stop()
        self.assertTrue(callable(getattr(self.worker, "_validate_child_runtime", None)), "Child runtime verification seam is missing")
        binding, spec = self.native_binding()
        changed = dict(spec, python_executable_path="UNBOUND_OTHER_PYTHON")
        with self.assertRaisesRegex(Exception, "CHILD_NATIVE_SPEC_BINDING_MISMATCH"):
            self.worker._validate_child_runtime(common, binding, {"native_spec": changed})


if __name__ == "__main__":
    unittest.main()
