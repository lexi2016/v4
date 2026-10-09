"""Metadata-only contracts; all snapshots and releases in these tests are synthetic."""
from __future__ import annotations

import copy
import contextlib
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "rff_saved_eval_contracts.py"
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location("rff_saved_eval_contracts", SOURCE)
    contracts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contracts)
else:
    contracts = None


class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contracts, "RFF saved-evaluation contract adapter is missing")

    def test_resources_are_explicit_and_never_reuse_historical_defaults(self):
        for value in ({}, {"cpu_threads": 4}, {"cpu_threads": True,
                "aggregate_process_tree_rss_bytes_max": 1000, "wall_seconds_max": 60,
                "sample_seconds": 0.05}):
            with self.assertRaises(contracts.SavedEvaluationError):
                contracts.validate_resources(value)
        value = {"cpu_threads": 8, "aggregate_process_tree_rss_bytes_max": 9000000000,
                 "wall_seconds_max": 600, "sample_seconds": 0.1}
        self.assertEqual(contracts.validate_resources(value), value)

    def test_budget_and_exposure_are_exact_not_truthy(self):
        value = contracts.execution_spec("NEW_SAVED_EVAL", {
            "cpu_threads": 4, "aggregate_process_tree_rss_bytes_max": 9000000000,
            "wall_seconds_max": 600, "sample_seconds": 0.05})
        contracts.validate_execution_spec(value)
        for key in contracts.ZERO_AUTHORIZATIONS:
            bad = copy.deepcopy(value)
            bad[key] = True
            with self.assertRaisesRegex(contracts.SavedEvaluationError, "ZERO"):
                contracts.validate_execution_spec(bad)
        for key, replacement in (("candidate_model_load_authorized", True),
                                 ("automatic_retry", True),
                                 ("evidence_ceiling", "PROMOTION"),
                                 ("evaluation_truth_decode_authorized", 2)):
            bad = copy.deepcopy(value)
            bad[key] = replacement
            with self.assertRaises(contracts.SavedEvaluationError):
                contracts.validate_execution_spec(bad)

    def test_fresh_outputs_cannot_overlap_any_bound_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            candidate = root / "candidate"
            candidate.mkdir()
            score = candidate / "scores.gz"
            score.write_bytes(b"opaque-score-snapshot")
            run = root / "recovery" / "execution" / "NEW"
            trace = root / "recovery" / "evidence" / "NEW.json"
            inputs = {"candidate_scores": {"path": str(score), "sha256": "0" * 64}}
            contracts.validate_new_paths(run, trace, candidate, inputs, require_new=True)
            for output, tr in ((candidate / "NEW", trace), (root, trace), (run, score)):
                with self.assertRaises(contracts.SavedEvaluationError):
                    contracts.validate_new_paths(output, tr, candidate, inputs, require_new=True)
            run.mkdir(parents=True)
            with self.assertRaisesRegex(contracts.SavedEvaluationError, "REENTRY"):
                contracts.validate_new_paths(run, trace, candidate, inputs, require_new=True)

    def test_exact_source_compilation_ignores_stale_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "bound.py"
            path.write_text("VALUE = 17\n")
            record = contracts.file_record(path)
            module = contracts.load_bound_module(record, "rff_synthetic_bound_source")
            self.assertEqual(module.VALUE, 17)
            path.write_text("VALUE = 18\n")
            with self.assertRaisesRegex(contracts.SavedEvaluationError, "SHA"):
                contracts.load_bound_module(record, "rff_synthetic_bound_source")
            sys.modules.pop("rff_synthetic_bound_source", None)

    def test_exclusive_json_never_overwrites_existing_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "receipt.json"
            digest = contracts.write_json_exclusive(path, {"a": 1})
            with self.assertRaises(FileExistsError):
                contracts.write_json_exclusive(path, {"a": 2})
            self.assertEqual(contracts.sha256_file(path), digest)
            self.assertEqual(json.loads(path.read_bytes()), {"a": 1})

    def test_old_pass_transcript_cannot_release_a_new_binding(self):
        self.assertTrue(hasattr(contracts, "verify_review_release"), "review identity validator is missing")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            review_path = root / "review.json"
            release_path = root / "release.json"
            spec_raw = b'{"spec":"synthetic"}\n'
            binding_raw = b'{"binding":"synthetic"}\n'
            binding = {"execution_id": "NEW", "candidate_execution_id": contracts.CANDIDATE,
                "route_id": contracts.ROUTE, "code_sha256": "a" * 64,
                "official_registry_path": str(root / "registry.jsonl"),
                "official_registry_sha256_before_start": "b" * 64,
                "expected_route_event_sha256_before_start": ["c" * 64],
                "resources": {"cpu_threads": 4},
                "parent_release_path": str(release_path),
                "reviewer_transcript_path": str(review_path)}
            common = {"execution_id": "NEW", "candidate_execution_id": contracts.CANDIDATE,
                "route_id": contracts.ROUTE,
                "run_spec_sha256": contracts.sha256_bytes(spec_raw),
                "input_binding_sha256": contracts.sha256_bytes(binding_raw),
                "source_code_sha256": binding["code_sha256"]}
            review = {**common, "schema": "F5_RFF_SAVED_EVAL_LOCAL_REVIEW_V1",
                "reviewer_agent": "independent-local-reviewer", "writer_agent": "local-controller",
                "reviewer_verdict": "PASS", "REVIEWED": "PASS", "BEHAVIOR_VERIFIED": "PASS",
                "scope": "EXACT_LOCAL_RFF_SAVED_EVALUATION_BINDING"}
            review_path.write_bytes(contracts.canonical_bytes(review))
            release = {**common, "schema": "F5_RFF_SAVED_EVAL_PARENT_RELEASE_V1", "active": True,
                "parent_authorization_id": "synthetic-test-only", "parent_controller_id": "local-controller",
                "reviewer_agent": review["reviewer_agent"],
                "reviewer_transcript_path": str(review_path),
                "reviewer_transcript_sha256": contracts.sha256_file(review_path),
                "saved_prediction_evaluation_authorized": True, "automatic_retry": False,
                "candidate_model_load_authorized": False, "evaluation_truth_decode_authorized": 1,
                **{key: 0 for key in contracts.ZERO_AUTHORIZATIONS},
                "resource_caps": binding["resources"], "safety": contracts.SAFETY,
                "official_registry_path": binding["official_registry_path"],
                "official_registry_sha256_before_start": "b" * 64,
                "expected_route_event_sha256_before_start": ["c" * 64]}
            release_path.write_bytes(contracts.canonical_bytes(release))
            contracts.verify_review_release(binding, spec_raw, binding_raw)
            review["source_code_sha256"] = "d" * 64
            review_path.write_bytes(contracts.canonical_bytes(review))
            release["reviewer_transcript_sha256"] = contracts.sha256_file(review_path)
            release_path.write_bytes(contracts.canonical_bytes(release))
            with self.assertRaisesRegex(contracts.SavedEvaluationError, "REVIEW_IDENTITY"):
                contracts.verify_review_release(binding, spec_raw, binding_raw)


class SyntheticPreparation:
    """An entirely generated metadata tree, including nonexistent data paths.

    PINS are patched only for the lifetime of a test. The production identities
    and the five source names are never written or replaced by test fixtures.
    No source in this tree is imported; the raising bodies detect that mistake.
    """

    def __init__(self, root: Path, *, validator_directory="contracts"):
        self.root = root.resolve()
        self.project = self.root / "synthetic 工厂"
        self.recovery = self.root / "saved evaluation"
        self.sources = self.root / "new source" / "src"
        self.original = self.project / "handoffs" / "old candidate"
        self.original.mkdir(parents=True)
        self.pins = dict(contracts.PINS)
        self.resources = {"cpu_threads": 3, "aggregate_process_tree_rss_bytes_max": 4567890123,
                          "wall_seconds_max": 321, "sample_seconds": 0.07}
        self.execution = "SYNTHETIC_METADATA_ONLY_EVAL"
        for name in contracts.SOURCE_NAMES:
            self.put(self.sources / (name + ".py"), b"raise AssertionError('source must not run during prepare')\n")

        self.batch = self.project / "research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927"
        self.contract_path = self.batch / "contracts/EXPERIMENT_CONTRACT.json"
        self.gates = {"development_primary": {"operator": ">", "value": 0.0},
                      "practical_base34": {"operator": ">=", "value": 0.03},
                      "promotion_now": False}
        self.contract_doc = {"schema": "F5_FULL64_RFF_LOGISTIC_CONTRACT_V1",
                             "route_id": contracts.ROUTE, "decision_gates": self.gates}
        self.record_json("experiment_contract", self.contract_path, self.contract_doc)
        self.spec_path = self.project / "handoffs/old/CANDIDATE_RUN_SPEC.json"
        self.old_spec = {"route_id": contracts.ROUTE, "execution_id": contracts.CANDIDATE,
                         "experiment_contract_sha256": self.pins["experiment_contract"],
                         "decision_gates": self.gates}
        self.record_json("candidate_spec", self.spec_path, self.old_spec)

        self.runtime_contract = self.project / "runtime/contracts/RUNTIME.json"
        self.runtime_doc = {"runtime_id": "SYNTHETIC_FROZEN_RUNTIME", "status": "FROZEN",
            "python": {"path": str(self.root / "never-open-python"),
                       "environment_policy": "REUSE_EXISTING_NO_INSTALL_DURING_RESEARCH_RUN"}}
        self.put_json(self.runtime_contract, self.runtime_doc)
        self.reference_path = self.batch / "contracts/NATIVE_REFERENCE.json"
        self.reference_doc = {"schema": "F5_FULL64_RFF_NATIVE_REFERENCE_RUNTIME_V1",
            "route_id": contracts.ROUTE,
            "runtime_contract": {"path": str(self.runtime_contract),
                                 "sha256": contracts.sha256_file(self.runtime_contract)}}
        self.put_json(self.reference_path, self.reference_doc)
        self.native_path = self.batch / "src/rff_native_runtime.py"
        self.put(self.native_path, b"raise AssertionError('native preflight must not run during prepare')\n")
        self.accepted_worker = self.root / "accepted PR5/rff_worker.py"
        self.record_source("accepted_worker", self.accepted_worker)
        self.metric_path = self.root / "frozen evaluator/spike5/metrics.py"
        self.record_source("frozen_metrics", self.metric_path,
                           "from .settings import CONTRACT\nraise AssertionError('do not import metrics')\n")
        self.put(self.metric_path.parent / "settings.py", b"CONTRACT = {'synthetic_cost': 17}\n")
        self.put(self.metric_path.parent / "__init__.py", b"# synthetic frozen package\n")
        self.score_aware = self.project / "research/hk_burst_f5/batches/full64_xendcg_r1_20260924/src/score_aware_metrics.py"
        self.record_source("score_aware_metrics", self.score_aware,
            f"from pathlib import Path\nF5_SOURCE_ROOT = Path({str(self.metric_path.parent.parent)!r})\n"
            "FROZEN_METRICS_PATH = F5_SOURCE_ROOT / 'spike5' / 'metrics.py'\n"
            "raise AssertionError('do not import score-aware evaluator')\n")
        self.resource_tree = self.project / "shared/resource_tree.py"
        self.record_source("resource_tree", self.resource_tree)
        self.official = {}
        for name in ("execution_guard", "registry_adapter", "builder", "validator"):
            directory = validator_directory if name == "validator" else "contracts"
            path = self.project / directory / (name + ".py")
            self.record_source(name, path)
            self.official[name] = contracts.file_record(path)
        self.policy_path = self.project / "contracts/EXPERIMENT_REGISTRY_APPEND_COMPATIBILITY_POLICY_V1.json"
        self.policy = {"official_builder": dict(self.official["builder"])}
        self.put_json(self.policy_path, self.policy)
        self.registry = self.project / "contracts/EXPERIMENT_REGISTRY.jsonl"
        self.events = [{"route_id": contracts.ROUTE, "experiment_id": contracts.ROUTE,
            "execution_id": contracts.CANDIDATE, "event_type": kind,
            "event_sha256": contracts.sha256_bytes(("synthetic " + kind).encode())}
            for kind in ("RUN_STARTED", "DECISION")]
        self.put(self.registry, b"".join(contracts.canonical_bytes(e) + b"\n" for e in self.events))

        self.binding_path = self.project / "handoffs/old/CANDIDATE_INPUT_BINDING.json"
        self.start_path = self.original / "CANDIDATE_START_RECEIPT.json"
        self.terminal_path = self.original / "CANDIDATE_TERMINAL_RECEIPT.json"
        self.old_binding = {"route_id": contracts.ROUTE, "execution_id": contracts.CANDIDATE,
            "input_binding_path": str(self.binding_path), "run_spec_path": str(self.spec_path),
            "run_spec_sha256": self.pins["candidate_spec"], "output_root": str(self.original),
            "start_receipt_path": str(self.start_path), "official_registry_path": str(self.registry),
            "experiment_contract_path": str(self.contract_path),
            "experiment_contract_sha256": self.pins["experiment_contract"],
            "evaluation_contract": dict(contracts.EVALUATION),
            "native_runtime_path": str(self.native_path),
            "native_runtime_sha256": contracts.sha256_file(self.native_path),
            "native_reference_contract_path": str(self.reference_path),
            "native_reference_contract_sha256": contracts.sha256_file(self.reference_path),
            "executable_helpers": {"native_runtime": contracts.file_record(self.native_path),
                                   "native_reference_contract": contracts.file_record(self.reference_path),
                                   "runtime_contract": contracts.file_record(self.runtime_contract)},
            "runtime_contract_path": str(self.runtime_contract),
            "resource_tree_path": str(self.resource_tree),
            # An immutable historical declaration is allowed to differ from the
            # new accepted helper. prepare must not rebind or execute old code.
            "resource_tree_sha256": "1" * 64,
            "code_files": {"score_aware_metrics": contracts.file_record(self.score_aware),
                           "rff_worker": {"path": str(self.project / "never-read-historical-worker.py"),
                                          "sha256": "2" * 64}},
            "official_helpers": self.official, "input_files": {}, "baseline_artifacts": {}}
        self.forbidden = {self.original / "CANDIDATE_MODEL.npz",
                          self.original / "CANDIDATE_RAW_SCORES.npy"}
        for name in ("eval_meta.csv.gz", "eval_calendar.csv.gz"):
            path = self.project / "never-read-inputs" / name
            self.old_binding["input_files"][name] = {"path": str(path), "sha256": contracts.sha256_bytes(name.encode())}
            self.forbidden.add(path)
        for arm in contracts.CONTROLS:
            artifact = {}
            for kind in ("scores", "top3"):
                name = f"{arm}_{kind}"
                path = self.project / "never-read-controls" / (name + ".csv.gz")
                self.pins[name] = contracts.sha256_bytes(("synthetic " + name).encode())
                artifact[kind + "_path"] = str(path)
                artifact[kind + "_sha256"] = self.pins[name]
                self.forbidden.add(path)
            self.old_binding["baseline_artifacts"][arm] = artifact
        for name, filename in (("candidate_scores", "CANDIDATE_SCORES.csv.gz"),
                               ("candidate_top3", "CANDIDATE_TOP3.csv.gz")):
            self.pins[name] = contracts.sha256_bytes(("synthetic " + name).encode())
            self.forbidden.add(self.original / filename)
        self.seal_path = self.original / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json"
        self.seal_doc = {"schema": "F5_FULL64_RFF_PREDICTION_SEAL_V1", "route_id": contracts.ROUTE,
            "execution_id": contracts.CANDIDATE, "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
            "score_kind": "RAW_LOGISTIC_DECISION_MARGIN", "probability_kind": "FITTED_LOGISTIC_SIGMOID_NO_CALIBRATOR",
            "predict_calls": 1, "grid_rows": contracts.EVALUATION["grid_rows"],
            "scoreable_rows": contracts.EVALUATION["scoreable_rows"], "evaluation_sessions": contracts.EVALUATION["sessions"],
            "evaluation_label_values_decoded": False, "safety": dict(contracts.SAFETY),
            "candidate_scores_sha256": self.pins["candidate_scores"], "candidate_top3_sha256": self.pins["candidate_top3"]}
        self.record_json("prediction_seal", self.seal_path, self.seal_doc)
        self.refresh_old_binding()
        self.config = {"project_root": str(self.project), "recovery_root": str(self.recovery),
            "execution_id": self.execution, "resources": self.resources,
            "candidate_binding_path": str(self.binding_path),
            "accepted_worker_path": str(self.accepted_worker), "frozen_metrics_path": str(self.metric_path)}

    @staticmethod
    def put(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def put_json(self, path, document):
        self.put(path, contracts.canonical_bytes(document) + b"\n")

    def record_json(self, name, path, document):
        self.put_json(path, document)
        self.pins[name] = contracts.sha256_file(path)

    def record_source(self, name, path, source=None):
        self.put(path, (source or f"raise AssertionError('synthetic {name} must not be imported')\n").encode())
        self.pins[name] = contracts.sha256_file(path)

    def refresh_old_binding(self):
        self.old_binding["code_sha256"] = contracts.sha256_bytes(contracts.canonical_bytes(self.old_binding["code_files"]))
        self.record_json("candidate_binding", self.binding_path, self.old_binding)
        self.start = {"schema": "F5_FULL64_XENDCG_CANDIDATE_START_RECEIPT_V1", "status": "RUN_STARTED_DURABLE",
            "route_id": contracts.ROUTE, "execution_id": contracts.CANDIDATE,
            "run_spec_sha256": self.pins["candidate_spec"], "input_binding_sha256": self.pins["candidate_binding"],
            "source_code_sha256": self.old_binding["code_sha256"], "start_event_sha256": self.events[0]["event_sha256"]}
        self.record_json("candidate_start", self.start_path, self.start)
        self.terminal = {"schema": "F5_FULL64_XENDCG_CANDIDATE_TERMINAL_RECEIPT_V1",
            "execution_id": contracts.CANDIDATE, "terminal_status": "CANNOT_CONFIRM",
            "terminal_event_sha256": self.events[1]["event_sha256"],
            "start_receipt_sha256": self.pins["candidate_start"]}
        self.record_json("candidate_terminal", self.terminal_path, self.terminal)

    @contextlib.contextmanager
    def active(self):
        with mock.patch.object(contracts, "PINS", self.pins), mock.patch.object(
                contracts, "__file__", str(self.sources / "rff_saved_eval_contracts.py")):
            yield self

    def prepare(self):
        result = contracts.prepare(self.config)
        self.new_spec = Path(result["run_spec_path"])
        self.new_binding = Path(result["input_binding_path"])
        return result

    def load(self):
        return contracts.load_documents(self.new_spec, self.new_binding)

    def mutate_binding(self, change):
        binding = json.loads(self.new_binding.read_bytes())
        change(binding)
        self.put_json(self.new_binding, binding)
        return binding


class PreparationRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = SyntheticPreparation(Path(self.temp.name))
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(self.fixture.active())

    def test_prepare_and_reload_are_metadata_only_exact_and_preserve_old_bytes(self):
        f = self.fixture
        old = {p: p.read_bytes() for p in (f.binding_path, f.spec_path, f.start_path,
                                         f.terminal_path, f.seal_path, f.registry)}
        native_pins = dict(contracts.PINS)
        opened = []
        original_open = Path.open
        def metadata_open(path, *args, **kwargs):
            opened.append(path)
            if path in f.forbidden:
                raise AssertionError(f"PREPARE_READ_DATA:{path}")
            return original_open(path, *args, **kwargs)
        with mock.patch.object(Path, "open", metadata_open):
            result = f.prepare()
            spec, binding, spec_raw, binding_raw = f.load()
        self.assertFalse(any(p.exists() for p in f.forbidden))
        self.assertFalse(result["data_rows_read"])
        self.assertFalse(result["registry_mutated"])
        self.assertFalse(result["execution_started"])
        self.assertEqual(old, {p: p.read_bytes() for p in old})
        self.assertEqual(contracts.PINS, native_pins)
        self.assertEqual(binding["resources"], f.resources)
        self.assertEqual(spec, contracts.execution_spec(f.execution, f.resources))
        self.assertEqual(result["input_binding_sha256"], contracts.sha256_bytes(binding_raw))
        self.assertEqual(binding["run_spec_sha256"], contracts.sha256_bytes(spec_raw))
        self.assertEqual(set(binding["code_files"]), set(contracts.SOURCE_NAMES))
        self.assertEqual(result["source_code_sha256"], contracts.sha256_bytes(contracts.canonical_bytes(binding["code_files"])))
        self.assertEqual(binding["expected_route_event_sha256_before_start"], [e["event_sha256"] for e in f.events])
        self.assertEqual(binding["official_registry_sha256_before_start"], contracts.sha256_bytes(old[f.registry]))
        self.assertNotIn(f.metric_path.parent / "never-read-model", opened)
        self.assertFalse(Path(binding["output_root"]).exists())
        self.assertFalse(Path(binding["parent_release_path"]).exists())

    def test_prepare_rejects_native_source_drift_against_immutable_old_binding(self):
        f = self.fixture
        f.native_path.write_bytes(b"# changed after the old execution\n")
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "SHA"):
            f.prepare()
        self.assertFalse(f.recovery.exists())

    def test_old_scope_needs_only_the_five_documented_counters_and_new_year_stays_fixed(self):
        f = self.fixture
        del f.old_binding["evaluation_contract"]["year"]
        f.refresh_old_binding()
        f.prepare()
        spec, binding, _, _ = f.load()
        self.assertEqual(spec["evaluation_contract"]["year"], 2024)
        self.assertEqual(binding["evaluation_contract"]["year"], 2024)

    def test_present_old_scope_year_cannot_contradict_the_frozen_2024_scope(self):
        f = self.fixture
        f.old_binding["evaluation_contract"]["year"] = 2023
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "EVALUATION_SCOPE.*year"):
            f.prepare()

    def test_prepare_cannot_rebind_the_frozen_contract_through_a_different_old_spec(self):
        f = self.fixture
        f.old_spec["experiment_contract_sha256"] = "9" * 64
        f.record_json("candidate_spec", f.spec_path, f.old_spec)
        f.old_binding["run_spec_sha256"] = f.pins["candidate_spec"]
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "SPEC_EXPERIMENT_CONTRACT"):
            f.prepare()

    def test_prepare_rejects_an_old_terminal_receipt_for_a_different_start(self):
        f = self.fixture
        f.terminal["start_receipt_sha256"] = "9" * 64
        f.record_json("candidate_terminal", f.terminal_path, f.terminal)
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "RECEIPT_CHAIN"):
            f.prepare()

    def test_prepare_never_evaluates_a_dynamic_metrics_path_expression(self):
        f = self.fixture
        marker = f.root / "forbidden-helper-execution"
        f.record_source("score_aware_metrics", f.score_aware,
            "from pathlib import Path\n"
            f"F5_SOURCE_ROOT = Path({str(f.metric_path.parent.parent)!r})\n"
            f"FROZEN_METRICS_PATH = Path({str(marker)!r}).write_text('must not execute')\n")
        f.old_binding["code_files"]["score_aware_metrics"] = contracts.file_record(f.score_aware)
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "PATH_LITERAL"):
            f.prepare()
        self.assertFalse(marker.exists())

    def test_prepare_rejects_old_runtime_contract_mirror_pointing_to_a_different_file(self):
        f = self.fixture
        duplicate = f.root / "other-runtime-contract.json"
        duplicate.write_bytes(f.runtime_contract.read_bytes())
        f.old_binding["executable_helpers"]["runtime_contract"]["path"] = str(duplicate)
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "ORIGINAL_RUNTIME_CONTRACT"):
            f.prepare()

    def test_prepare_rejects_score_aware_helper_not_identified_by_the_old_manifest(self):
        f = self.fixture
        duplicate = f.root / "other-score-aware.py"
        duplicate.write_bytes(f.score_aware.read_bytes())
        f.old_binding["code_files"]["score_aware_metrics"]["path"] = str(duplicate)
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "ORIGINAL_SCORE_AWARE"):
            f.prepare()

    def test_prepare_rejects_native_reference_mirror_disagreement(self):
        f = self.fixture
        f.old_binding["executable_helpers"]["native_reference_contract"]["sha256"] = "9" * 64
        f.refresh_old_binding()
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "NATIVE.*SHA"):
            f.prepare()

    def test_prepare_resolves_the_official_validators_actual_implicit_policy_path(self):
        other = SyntheticPreparation(Path(self.temp.name) / "alternate", validator_directory="official_tools")
        with other.active():
            other.prepare()
            _, binding, _, _ = other.load()
        self.assertEqual(binding["metadata_files"]["append_policy"]["path"], str(other.policy_path))

    def test_prepare_rejects_policy_builder_identity_disagreement(self):
        f = self.fixture
        f.policy["official_builder"]["sha256"] = "9" * 64
        f.put_json(f.policy_path, f.policy)
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "POLICY.*BUILDER"):
            f.prepare()

    def test_prepare_rejects_a_copy_of_metrics_outside_the_frozen_evaluator_path(self):
        f = self.fixture
        other = f.root / "lookalike evaluator/metrics.py"
        f.put(other, f.metric_path.read_bytes())
        for name in ("settings.py", "__init__.py"):
            f.put(other.parent / name, (f.metric_path.parent / name).read_bytes())
        f.config["frozen_metrics_path"] = str(other)
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "FROZEN_METRICS.*PATH"):
            f.prepare()

    def test_prepare_rejects_an_already_registered_execution_without_writing_outputs(self):
        f = self.fixture
        with f.registry.open("ab") as stream:
            stream.write(contracts.canonical_bytes({"execution_id": f.execution}) + b"\n")
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "EXECUTION_ALREADY_PRESENT"):
            f.prepare()
        self.assertFalse(f.recovery.exists())

    def test_load_rejects_candidate_score_path_rebound_even_with_the_frozen_digest(self):
        f = self.fixture
        f.prepare()
        f.mutate_binding(lambda b: b["input_files"]["candidate_scores"].update(path=str(f.root / "elsewhere/scores.gz")))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "CANDIDATE.*PATH"):
            f.load()

    def test_load_rejects_old_spec_relocated_with_identical_bytes(self):
        f = self.fixture
        f.prepare()
        duplicate = f.root / "old-spec-copy.json"
        duplicate.write_bytes(f.spec_path.read_bytes())
        f.mutate_binding(lambda b: b["metadata_files"]["candidate_spec"].update(path=str(duplicate)))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "ORIGINAL.*SPEC"):
            f.load()

    def test_load_rejects_native_runtime_contract_rebound_away_from_the_reference(self):
        f = self.fixture
        f.prepare()
        duplicate = f.root / "runtime-copy.json"
        duplicate.write_bytes(f.runtime_contract.read_bytes())
        f.mutate_binding(lambda b: b["metadata_files"]["native_runtime_contract"].update(path=str(duplicate)))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "RUNTIME.*REFERENCE"):
            f.load()

    def test_load_rejects_frozen_settings_relocated_outside_the_metrics_package(self):
        f = self.fixture
        f.prepare()
        duplicate = f.root / "settings-copy.py"
        duplicate.write_bytes((f.metric_path.parent / "settings.py").read_bytes())
        f.mutate_binding(lambda b: b["executable_helpers"]["frozen_settings"].update(path=str(duplicate)))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "FROZEN.*PACKAGE"):
            f.load()

    def test_load_rejects_release_and_review_paths_outside_the_reviewed_recovery_root(self):
        f = self.fixture
        f.prepare()
        original = f.new_binding.read_bytes()
        for field in ("parent_release_path", "reviewer_transcript_path"):
            with self.subTest(field=field):
                f.new_binding.write_bytes(original)
                f.mutate_binding(lambda b: b.update({field: str(f.root / (field + ".json"))}))
                with self.assertRaisesRegex(contracts.SavedEvaluationError, "EXECUTION_PATH"):
                    f.load()

    def test_load_rejects_spec_and_binding_relocated_away_from_the_declared_recovery(self):
        f = self.fixture
        f.prepare()
        spec_copy, binding_copy = f.root / "spec-copy.json", f.root / "binding-copy.json"
        spec_copy.write_bytes(f.new_spec.read_bytes())
        binding = json.loads(f.new_binding.read_bytes())
        binding.update(run_spec_path=str(spec_copy), input_binding_path=str(binding_copy))
        f.put_json(binding_copy, binding)
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "EXECUTION_PATH"):
            contracts.load_documents(spec_copy, binding_copy)

    def test_load_rejects_registry_path_rebound_away_from_the_old_official_ledger(self):
        f = self.fixture
        f.prepare()
        f.mutate_binding(lambda b: b.update(official_registry_path=str(f.root / "other_registry.jsonl")))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "REGISTRY.*PATH"):
            f.load()

    def test_prepare_rejects_a_seal_for_different_saved_scores(self):
        f = self.fixture
        f.seal_doc["candidate_scores_sha256"] = "9" * 64
        f.record_json("prediction_seal", f.seal_path, f.seal_doc)
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "SEAL.*ARTIFACT"):
            f.prepare()

    def test_load_rejects_source_manifest_drift_and_resource_rebinding(self):
        f = self.fixture
        f.prepare()
        original = f.new_binding.read_bytes()
        f.mutate_binding(lambda b: b["resources"].update(cpu_threads=4))
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "SCOPE_MISMATCH:resources"):
            f.load()
        f.new_binding.write_bytes(original)
        source = f.sources / "rff_saved_eval_frames.py"
        source.write_bytes(b"# new unreviewed source\n")
        with self.assertRaisesRegex(contracts.SavedEvaluationError, "SHA"):
            f.load()

    def test_load_preserves_owner_reentry_for_metadata_check_after_durable_start(self):
        f = self.fixture
        f.prepare()
        _, binding, _, _ = f.load()
        output = Path(binding["output_root"])
        output.mkdir(parents=True)
        Path(binding["resource_trace_path"]).parent.mkdir(parents=True)
        Path(binding["resource_trace_path"]).write_bytes(b"synthetic monitor evidence\n")
        Path(binding["start_receipt_path"]).write_bytes(b"synthetic durable start receipt\n")
        f.load()


if __name__ == "__main__":
    unittest.main()
