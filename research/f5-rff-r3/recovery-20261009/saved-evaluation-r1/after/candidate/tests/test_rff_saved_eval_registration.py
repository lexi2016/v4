"""RFF registry integration on generated data and the packaged official helpers.

All registry bytes, contracts, policy and worker-source stand-ins live in a
TemporaryDirectory. The actual official adapter, guard, builder and compatibility
validator are copied byte-for-byte from the source attachment; no live registry,
candidate artifacts, truth, model, candidate CLI or accepted join tests are used.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "inputs/attachments/official_helpers"
REGISTRATION_PATH = ROOT / "candidate/src/rff_saved_eval_registration.py"
ROUTE = "F5_FULL64_RFF_LOGISTIC_R1_20260927"
CANDIDATE = "F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01"
EXECUTION = "F5_FULL64_RFF_LOGISTIC_R1_20260927_SAVED_EVAL_SYNTHETIC_01"
COUNTERS = ("fit_calls", "real_fit_returned_count", "predict_calls",
            "control_fit_calls", "control_predict_calls", "calibrator_fit_calls", "model_load_calls")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def ref(path):
    return {"path": str(path), "sha256": sha(path.read_bytes())}


class SyntheticOfficialRegistry:
    """A complete synthetic compatibility-policy fixture, not a registry stub."""

    def __init__(self, registration):
        self.registration = registration
        self.tmp = tempfile.TemporaryDirectory(prefix="rff-saved-eval-registry-")
        self.root = Path(self.tmp.name).resolve()
        self.helpers = self.root / "helpers"
        self.contracts = self.root / "contracts"
        self.helpers.mkdir()
        self.contracts.mkdir()
        self.old_core = sys.modules.get("execution_guard_core")
        for name in ("execution_guard_core.py", "registry_adapter.py",
                     "build_experiment_registry_backfill_20260821.py",
                     "validate_experiment_registry_append_compatibility_v1.py"):
            shutil.copyfile(HELPERS / name, self.helpers / name)
        self.guard_module = load(self.helpers / "execution_guard_core.py", "execution_guard_core")
        self.builder_path = self.helpers / "build_experiment_registry_backfill_20260821.py"
        self.builder = load(self.builder_path, "synthetic_rff_official_builder")
        self.fixture_contract = self.contracts / "SYNTHETIC_OLD_CONTRACT.json"
        write_json(self.fixture_contract, {"synthetic_only": True})

        def old_spec(event_id, execution_id, event_type, *, rff=False):
            return {
                "schema_version": "1.0", "registry_event_id": event_id,
                "execution_id": execution_id,
                "experiment_id": ROUTE if rff else "SYNTHETIC_HISTORY",
                "route_id": ROUTE if rff else "SYNTHETIC_HISTORY",
                "registration_mode": "LIVE_EXECUTION", "event_type": event_type,
                "arm": "SYNTHETIC_OLD_CANDIDATE", "stage": event_type,
                "contract_path": str(self.fixture_contract),
                "artifact_paths": [str(self.fixture_contract)],
                "input_binding_sha256": "1" * 64,
                "input_identity": {"experiment_id": ROUTE, "arm": "SYNTHETIC_OLD_CANDIDATE",
                                   "contract_sha256": sha(self.fixture_contract.read_bytes()),
                                   "input_binding_sha256": "1" * 64},
                "deterministic_metrics": {
                    "execution_kind": "REAL_FIT", "planned_real_fit_count": 1,
                    "real_fit_budget_debit": 1,
                    "fit_call_entered": event_type == "TERMINAL",
                    "real_fit_returned_count": 1 if event_type == "TERMINAL" else 0,
                },
                "decision": "CANNOT_CONFIRM" if event_type == "TERMINAL" else "RUNNING",
            }

        legacy_specs = [old_spec(f"synthetic-history-{i}", f"synthetic-history-{i}",
                                 "SYNTHETIC_METADATA") for i in range(644)]
        legacy = self.builder.materialize(legacy_specs)
        legacy_raw = self.builder._registry_payload(legacy)
        old_events = self.builder.materialize([
            old_spec(f"{CANDIDATE}_RUN_STARTED", CANDIDATE, "RUN_STARTED", rff=True),
            old_spec(f"{CANDIDATE}_TERMINAL", CANDIDATE, "TERMINAL", rff=True),
        ], starting_previous_sha=legacy[-1]["event_sha256"])
        self.before = legacy_raw + self.builder._registry_payload(old_events)
        self.registry_path = self.contracts / "SYNTHETIC_REGISTRY.jsonl"
        self.registry_path.write_bytes(self.before)
        policy_path = self.contracts / "EXPERIMENT_REGISTRY_APPEND_COMPATIBILITY_POLICY_V1.json"
        write_json(policy_path, {
            "synthetic_only": True,
            "official_builder": ref(self.builder_path),
            "legacy_prefix": {"event_count": 644, "size_bytes": len(legacy_raw),
                              "sha256": sha(legacy_raw), "head_event_sha256": legacy[-1]["event_sha256"]},
            "legacy_schema_debt": {
                "events_with_debt": 0, "required_fields_missing": 0,
                "null_reason_missing": 0, "missing_or_null_registry_event_id": 0,
                "nonempty_registry_event_id": 644, "required_fields_missing_ranges": [],
                "null_reason_missing_ranges": [], "records_sha256": sha(canonical([])),
            },
            "grandfathered_current_snapshot": {
                "anchor": {"event_count": 646, "size_bytes": len(self.before),
                           "sha256": sha(self.before), "head_event_sha256": old_events[-1]["event_sha256"]},
                "line_range_1_based": [645, 646], "strict_suffix_start_line_1_based": 647,
            },
        })
        self.adapter_module = load(self.helpers / "registry_adapter.py", "synthetic_rff_official_adapter")
        self.worker_source = self.root / "SYNTHETIC_WORKER.py"
        self.worker_source.write_text("# Synthetic evaluation-only source; no model operations.\n")
        self.run_spec_path = self.contracts / "RUN_SPEC.json"
        self.binding_path = self.contracts / "INPUT_BINDING.json"
        self.start_receipt_path = self.root / "execution" / EXECUTION / "EVALUATION_START_RECEIPT.json"
        write_json(self.run_spec_path, {
            "synthetic_only": True, "route_id": ROUTE, "execution_id": EXECUTION,
            "fit_calls_authorized": 0, "predict_calls_authorized": 0,
            "control_fit_calls_authorized": 0, "control_predict_calls_authorized": 0,
            "calibrator_fit_calls_authorized": 0, "model_load_calls_authorized": 0,
            "candidate_model_load_authorized": False,
        })
        self.binding = {
            "route_id": ROUTE, "execution_id": EXECUTION, "candidate_execution_id": CANDIDATE,
            "code_files": {"registration": ref(REGISTRATION_PATH), "worker": ref(self.worker_source)},
            "executable_helpers": {},
            "official_helpers": {
                "execution_guard": ref(self.helpers / "execution_guard_core.py"),
                "registry_adapter": ref(self.helpers / "registry_adapter.py"),
                "builder": ref(self.builder_path),
                "validator": ref(self.helpers / "validate_experiment_registry_append_compatibility_v1.py"),
                "compatibility_policy": ref(policy_path),
            },
            "official_registry_path": str(self.registry_path),
            "official_registry_sha256_before_start": sha(self.before),
            "expected_previous_event_sha256": old_events[-1]["event_sha256"],
            "expected_route_event_sha256_before_start": [event["event_sha256"] for event in old_events],
            "start_receipt_path": str(self.start_receipt_path),
        }
        self.binding["code_sha256"] = sha(canonical(self.binding["code_files"]))
        self.rebuild()

    def rebuild(self):
        write_json(self.binding_path, self.binding)
        self.spec_sha = sha(self.run_spec_path.read_bytes())
        self.binding_sha = sha(self.binding_path.read_bytes())
        adapter_class = self.registration.build_official_adapter_class(
            self.adapter_module, binding=self.binding,
            run_spec_path=self.run_spec_path, input_binding_path=self.binding_path,
            run_spec_sha256=self.spec_sha, input_binding_sha256=self.binding_sha,
        )
        self.adapter = adapter_class(
            registry_path=self.registry_path, contract_path=self.run_spec_path,
            input_binding_path=self.binding_path,
            artifact_paths=[Path(item["path"]) for category in
                            ("code_files", "executable_helpers", "official_helpers")
                            for item in self.binding[category].values()],
            builder_path=self.builder_path,
            validator_path=self.helpers / "validate_experiment_registry_append_compatibility_v1.py",
            event_profile=self.registration.event_profile(self.binding),
        )
        self.guard = self.guard_module.ExecutionGuard(self.adapter, experiment_id=ROUTE, max_real_fit_debits=1)

    def events(self):
        with self.adapter._locked():
            return self.adapter._read_validated()[1]

    def claim(self, *, receipt=True):
        claim = self.guard.claim_no_fit(execution_id=EXECUTION, arm="SAVED_RFF_EVALUATION_ONLY",
                                        contract_sha256=self.spec_sha, input_binding_sha256=self.binding_sha)
        if receipt:
            self.write_start_receipt()
        return claim

    def write_start_receipt(self):
        start = self.events()[-1]
        write_json(self.start_receipt_path, {
            "status": "RUN_STARTED_DURABLE", "execution_id": EXECUTION,
            "candidate_execution_id": CANDIDATE, "route_id": ROUTE,
            "run_spec_sha256": self.spec_sha, "input_binding_sha256": self.binding_sha,
            "source_code_sha256": self.binding["code_sha256"],
            "start_event_sha256": start["event_sha256"],
            "official_registry_sha256_after_start": sha(self.registry_path.read_bytes()),
        })

    def terminal(self, claim, *, status="COMPLETED", known=True):
        observed = {key: 0 if known else None for key in COUNTERS}
        observed.update(status="KNOWN" if known else "UNKNOWN",
                        fit_call_entered=False if known else None,
                        candidate_model_loaded=False if known else None)
        return {
            "event_type": "TERMINAL",
            **{key: getattr(claim, key) for key in
               ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256")},
            "execution_kind": "NO_FIT_ENGINEERING_CANARY",
            "planned_real_fit_count": 0, "real_fit_budget_debit": 0,
            "terminal_status": status, "fit_call_entered": False if known else None,
            "real_fit_returned_count": 0 if known else None,
            "observed_worker_accounting": observed,
            "truth_access": "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL" if known else "CANNOT_CONFIRM",
            "sealed_status": "EXPOSED_2024_POST_SEAL_EVALUATION",
            "truth_positive_denominator": 126 if status == "COMPLETED" else None,
            "selection_slots": 738 if status == "COMPLETED" else None,
            "truth_accounting": {"decode_attempts": 1, "decode_completed": 1 if known else None},
            "evaluation_metrics": {"metrics_computed": status == "COMPLETED"},
        }

    def append_unrelated_event(self):
        events = self.events()
        extra = self.builder.materialize([{
            "schema_version": "1.0", "registry_event_id": "synthetic-unrelated-after-bind",
            "execution_id": "synthetic-unrelated-after-bind", "event_type": "RUN_STARTED",
            "registration_mode": "LIVE_EXECUTION", "route_id": "SYNTHETIC_OTHER_ROUTE",
            "contract_path": str(self.fixture_contract), "artifact_paths": [str(self.fixture_contract)],
        }], starting_previous_sha=events[-1]["event_sha256"])
        self.registry_path.write_bytes(self.registry_path.read_bytes() + self.builder._registry_payload(extra))

    def close(self):
        if self.old_core is None:
            sys.modules.pop("execution_guard_core", None)
        else:
            sys.modules["execution_guard_core"] = self.old_core
        self.tmp.cleanup()


class RffSavedEvalRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(REGISTRATION_PATH.is_file(), "RFF route registry adapter has not been implemented")
        self.registration = load(REGISTRATION_PATH, "rff_saved_eval_registration_under_test")
        self.fixture = SyntheticOfficialRegistry(self.registration)
        self.addCleanup(self.fixture.close)

    def test_profile_keeps_rff_route_and_exposed_evidence_ceiling(self):
        profile = self.registration.event_profile(self.fixture.binding)
        self.assertEqual(profile["route_id"], ROUTE)
        self.assertEqual(profile["start_stage"], "RFF_SAVED_EVALUATION_RUN_STARTED")
        self.assertEqual(profile["terminal_stage"], "RFF_SAVED_EVALUATION_TERMINAL")
        self.assertIn(CANDIDATE, profile["signal_scope"])
        self.assertEqual(profile["evidence_level"], "DIRECTION_ONLY")

    def test_zero_debit_lifecycle_preserves_existing_fit_and_exact_prefix(self):
        f = self.fixture
        claim = f.claim()
        f.adapter.terminalize(claim, f.terminal(claim))
        self.assertTrue(f.registry_path.read_bytes().startswith(f.before))
        new = f.events()[646:]
        self.assertEqual([row["event_type"] for row in new], ["RUN_STARTED", "TERMINAL"])
        self.assertEqual(new[1]["previous_event_sha256"], new[0]["event_sha256"])
        summary = f.guard.accounting()
        self.assertEqual(summary.real_fit_budget_debit_count, 1)
        self.assertEqual(summary.returned_fit_count_lower_bound, 1)
        self.assertEqual(summary.no_fit_started_count, 1)
        self.assertEqual(summary.no_fit_terminal_count, 1)
        self.assertEqual(new[1]["candidate_execution_id"], CANDIDATE)
        self.assertFalse(new[1]["promotion_now"])
        self.assertTrue(new[1]["research_only"])
        self.assertFalse(new[1]["production_allowed"])

    def test_existing_execution_cannot_be_claimed_again(self):
        f = self.fixture
        f.claim()
        raw = f.registry_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "EXECUTION_ID_ALREADY_REGISTERED"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), raw)

    def test_nonzero_or_boolean_debits_are_rejected_before_append(self):
        f = self.fixture
        base = dict(event_type="RUN_STARTED", experiment_id=ROUTE, execution_id=EXECUTION,
                    arm="SAVED_RFF_EVALUATION_ONLY", contract_sha256=f.spec_sha,
                    input_binding_sha256=f.binding_sha, execution_kind="NO_FIT_ENGINEERING_CANARY",
                    planned_real_fit_count=0, real_fit_budget_debit=0)
        for key, value in (("planned_real_fit_count", 1), ("planned_real_fit_count", False),
                           ("real_fit_budget_debit", 1), ("real_fit_budget_debit", False),
                           ("execution_kind", "REAL_FIT"), ("experiment_id", "ANOTHER_ROUTE")):
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(RuntimeError, "START_IDENTITY_OR_ZERO_DEBIT_MISMATCH"):
                    f.adapter.claim_run_started(dict(base, **{key: value}), max_real_fit_debits=1)
                self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_registry_change_since_binding_rejects_start(self):
        f = self.fixture
        f.append_unrelated_event()
        raw = f.registry_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "REGISTRY_PREFIX_CHANGED"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), raw)

    def test_route_prefix_and_previous_tail_are_both_required(self):
        f = self.fixture
        for key, value, message in (
            ("expected_route_event_sha256_before_start", [], "ROUTE_PREFIX_MISMATCH"),
            ("expected_previous_event_sha256", "f" * 64, "PREVIOUS_EVENT_SHA_MISMATCH"),
        ):
            original = f.binding[key]
            with self.subTest(key=key):
                f.binding[key] = value
                f.rebuild()
                with self.assertRaisesRegex(RuntimeError, message):
                    f.claim(receipt=False)
                self.assertEqual(f.registry_path.read_bytes(), f.before)
            f.binding[key] = original

    def test_source_drift_before_start_never_appends(self):
        f = self.fixture
        f.worker_source.write_text("# drifted source\n")
        with self.assertRaisesRegex(RuntimeError, "BOUND_SOURCE_DRIFT"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_mutable_binding_object_does_not_change_frozen_scope(self):
        f = self.fixture
        f.binding["route_id"] = "UNBOUND_ROUTE"
        claim = f.claim()
        self.assertEqual(claim.experiment_id, ROUTE)
        self.assertEqual(f.events()[-1]["route_id"], ROUTE)

    def test_binding_bytes_drift_never_appends(self):
        f = self.fixture
        f.binding_path.write_bytes(f.binding_path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "INPUT_BINDING_CHANGED"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_source_drift_rejects_success_and_closes_failure_with_exact_evidence(self):
        f = self.fixture
        claim = f.claim()
        expected = ref(f.worker_source)
        f.worker_source.write_text("# changed after RUN_STARTED\n")
        observed_sha = sha(f.worker_source.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "SOURCE_DRIFT_REQUIRES_CANNOT_CONFIRM"):
            f.adapter.terminalize(claim, f.terminal(claim))
        self.assertEqual(len(f.events()), 647)
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        event = f.events()[-1]
        drift = event["deterministic_metrics"]["source_drift"]
        self.assertEqual(drift["status"], "DRIFT_DETECTED")
        self.assertEqual(drift["files"], [{"category": "code_files", "name": "worker",
            "path": expected["path"], "bound_sha256": expected["sha256"],
            "observed_sha256": observed_sha, "state": "SHA_MISMATCH"}])
        self.assertEqual(event["decision"], "CANNOT_CONFIRM")
        self.assertEqual(event["code_sha256"], f.binding["code_sha256"])
        self.assertFalse(event["evaluation_metrics"]["metrics_computed"])
        self.assertTrue(f.registry_path.read_bytes().startswith(f.before))

    def test_missing_source_can_terminalize_failure_without_fabricating_artifact(self):
        f = self.fixture
        claim = f.claim()
        f.worker_source.unlink()
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        event = f.events()[-1]
        self.assertEqual(event["deterministic_metrics"]["source_drift"]["files"][0]["state"], "MISSING")
        self.assertNotIn(str(f.worker_source), event["artifact_path"])

    def test_spec_drift_cannot_be_disguised_as_source_failure_terminal(self):
        f = self.fixture
        claim = f.claim()
        f.run_spec_path.write_bytes(f.run_spec_path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "RUN_SPEC_CHANGED"):
            f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        self.assertEqual(len(f.events()), 647)

    def test_unknown_observations_are_preserved_separately_from_budget_accounting(self):
        f = self.fixture
        claim = f.claim()
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM", known=False))
        event = f.events()[-1]
        metrics = event["deterministic_metrics"]
        self.assertEqual(metrics["real_fit_budget_debit"], 0)
        self.assertEqual(metrics["fit_accounting_basis"], "STATIC_EVALUATION_ONLY_CONTRACT")
        self.assertEqual(metrics["actual_fit_count_status"], "CANNOT_CONFIRM_WORKER_OBSERVATION_MISSING")
        self.assertEqual(metrics["observed_worker_accounting"]["status"], "UNKNOWN")
        self.assertIsNone(metrics["observed_worker_accounting"]["fit_calls"])
        self.assertIsNone(metrics["observed_worker_accounting"]["real_fit_returned_count"])
        self.assertIsNone(metrics["truth_accounting"]["decode_completed"])
        summary = f.guard.accounting()
        self.assertEqual(summary.real_fit_budget_debit_count, 1)
        self.assertEqual(summary.no_fit_terminal_count, 1)

    def test_unknown_observation_cannot_support_completed_terminal(self):
        f = self.fixture
        claim = f.claim()
        with self.assertRaisesRegex(RuntimeError, "COMPLETED_REQUIRES_OBSERVED_ZERO_ACTIVITY"):
            f.adapter.terminalize(claim, f.terminal(claim, known=False))
        self.assertEqual(len(f.events()), 647)

    def test_observed_nonzero_activity_is_never_relabelled_zero(self):
        f = self.fixture
        claim = f.claim()
        event = f.terminal(claim, status="CANNOT_CONFIRM")
        event["observed_worker_accounting"]["fit_calls"] = 1
        with self.assertRaisesRegex(RuntimeError, "OBSERVED_ACTIVITY_VIOLATES_ZERO_CONTRACT"):
            f.adapter.terminalize(claim, event)
        self.assertEqual(len(f.events()), 647)

    def test_missing_start_receipt_allows_only_failure_close(self):
        f = self.fixture
        claim = f.claim(receipt=False)
        with self.assertRaisesRegex(RuntimeError, "START_RECEIPT_MISSING"):
            f.adapter.terminalize(claim, f.terminal(claim))
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM", known=False))
        self.assertEqual(f.events()[-1]["stop_reason"], "START_RECEIPT_MISSING_AFTER_DURABLE_START")

    def test_start_append_succeeded_then_raised_can_be_closed_once_by_owner(self):
        f = self.fixture
        original = f.adapter._append_unlocked

        def append_then_raise(raw, events, spec):
            original(raw, events, spec)
            raise OSError("synthetic failure after durable append")

        f.adapter._append_unlocked = append_then_raise
        with self.assertRaisesRegex(OSError, "after durable append"):
            f.claim(receipt=False)
        self.assertEqual(len(f.events()), 647)
        f.adapter._append_unlocked = original
        recovered = f.guard_module.ExecutionClaim(ROUTE, EXECUTION, "SAVED_RFF_EVALUATION_ONLY",
            f.spec_sha, f.binding_sha, "NO_FIT_ENGINEERING_CANARY", 0)
        f.adapter.terminalize(recovered, f.terminal(recovered, status="CANNOT_CONFIRM", known=False))
        with self.assertRaisesRegex(RuntimeError, "TERMINAL_LIFECYCLE_INVALID"):
            f.adapter.terminalize(recovered, f.terminal(recovered, status="CANNOT_CONFIRM"))
        self.assertEqual(len(f.events()), 648)

    def test_terminal_append_succeeded_then_raised_is_not_automatically_retried(self):
        f = self.fixture
        claim = f.claim()
        original = f.adapter._append_unlocked

        def append_then_raise(raw, events, spec):
            original(raw, events, spec)
            raise OSError("synthetic terminal append returned error")

        f.adapter._append_unlocked = append_then_raise
        with self.assertRaisesRegex(OSError, "returned error"):
            f.adapter.terminalize(claim, f.terminal(claim))
        self.assertEqual(len(f.events()), 648)
        f.adapter._append_unlocked = original
        with self.assertRaisesRegex(RuntimeError, "TERMINAL_LIFECYCLE_INVALID"):
            f.adapter.terminalize(claim, f.terminal(claim))
        self.assertEqual(len(f.events()), 648)

    def test_global_registry_append_after_start_blocks_terminal(self):
        f = self.fixture
        claim = f.claim()
        f.append_unrelated_event()
        raw = f.registry_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "REGISTRY_CHANGED_AFTER_START"):
            f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        self.assertEqual(f.registry_path.read_bytes(), raw)

    def test_safety_flag_cannot_be_relaxed_at_terminal(self):
        f = self.fixture
        claim = f.claim()
        event = dict(f.terminal(claim), production_allowed=True)
        with self.assertRaisesRegex(RuntimeError, "SAFETY_FLAG_MISMATCH"):
            f.adapter.terminalize(claim, event)
        self.assertEqual(len(f.events()), 647)

    def test_model_load_numeric_count_cannot_disagree_with_boolean_flag(self):
        f = self.fixture
        claim = f.claim()
        event = f.terminal(claim, status="CANNOT_CONFIRM")
        event["observed_worker_accounting"]["model_load_calls"] = 1
        with self.assertRaisesRegex(RuntimeError, "OBSERVED_ACTIVITY_VIOLATES_ZERO_CONTRACT:model_load_calls"):
            f.adapter.terminalize(claim, event)
        self.assertEqual(len(f.events()), 647)

    def test_start_cannot_hide_nonzero_observed_activity(self):
        f = self.fixture
        event = dict(event_type="RUN_STARTED", experiment_id=ROUTE, execution_id=EXECUTION,
                     arm="SAVED_RFF_EVALUATION_ONLY", contract_sha256=f.spec_sha,
                     input_binding_sha256=f.binding_sha, execution_kind="NO_FIT_ENGINEERING_CANARY",
                     planned_real_fit_count=0, real_fit_budget_debit=0, fit_calls=1)
        with self.assertRaisesRegex(RuntimeError, "OBSERVED_ACTIVITY_VIOLATES_ZERO_CONTRACT:fit_calls"):
            f.adapter.claim_run_started(event, max_real_fit_debits=1)
        self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_static_zero_accounting_requires_an_actual_zero_authorization_spec(self):
        f = self.fixture
        spec = json.loads(f.run_spec_path.read_bytes())
        spec["fit_calls_authorized"] = 1
        write_json(f.run_spec_path, spec)
        f.rebuild()
        with self.assertRaisesRegex(RuntimeError, "SPEC_NOT_ZERO_ACTIVITY"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_boolean_claim_debit_cannot_masquerade_as_zero_integer(self):
        f = self.fixture
        original = f.claim()
        forged = replace(original, real_fit_budget_debit=False)
        with self.assertRaisesRegex(RuntimeError, "TERMINAL_NOT_ZERO_DEBIT"):
            f.adapter.terminalize(forged, f.terminal(forged, status="CANNOT_CONFIRM"))
        self.assertEqual(len(f.events()), 647)

    def test_parent_release_drift_before_start_is_checked_inside_claim(self):
        f = self.fixture
        release = f.contracts / "PARENT_RELEASE.json"
        write_json(release, {"synthetic_only": True, "authorization": "reviewed"})
        f.adapter.authorization_records = {"release": ref(release)}
        f.adapter.artifact_paths += (release,)
        write_json(release, {"synthetic_only": True, "authorization": "changed"})
        with self.assertRaisesRegex(RuntimeError, "BOUND_SOURCE_DRIFT"):
            f.claim(receipt=False)
        self.assertEqual(f.registry_path.read_bytes(), f.before)

    def test_release_drift_after_start_keeps_original_authorization_and_allows_failure(self):
        f = self.fixture
        release = f.contracts / "PARENT_RELEASE.json"
        write_json(release, {"synthetic_only": True, "authorization": "reviewed"})
        expected = ref(release)
        f.adapter.authorization_records = {"release": expected}
        f.adapter.artifact_paths += (release,)
        claim = f.claim()
        write_json(release, {"synthetic_only": True, "authorization": "changed"})
        # The caller cannot redefine the expectation after the durable start.
        f.adapter.authorization_records = {"release": ref(release)}
        with self.assertRaisesRegex(RuntimeError, "SOURCE_DRIFT_REQUIRES_CANNOT_CONFIRM"):
            f.adapter.terminalize(claim, f.terminal(claim))
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        start, terminal = f.events()[-2:]
        self.assertEqual(start["authorization_records"], {"release": expected})
        self.assertEqual(terminal["authorization_records"], {"release": expected})
        drift = terminal["deterministic_metrics"]["source_drift"]["files"]
        self.assertEqual(drift[0]["category"], "authorization_records")
        self.assertEqual(drift[0]["bound_sha256"], expected["sha256"])
        self.assertEqual(drift[0]["observed_sha256"], sha(release.read_bytes()))
        self.assertEqual(terminal["decision"], "CANNOT_CONFIRM")

    def test_metadata_dependency_drift_blocks_success_and_is_preserved_in_failure(self):
        f = self.fixture
        native_ref = f.contracts / "NATIVE_REFERENCE.json"
        write_json(native_ref, {"synthetic_only": True, "version": 1})
        f.binding["metadata_files"] = {"native_reference": ref(native_ref)}
        f.rebuild()
        f.adapter.artifact_paths += (native_ref,)
        claim = f.claim()
        write_json(native_ref, {"synthetic_only": True, "version": 2})
        with self.assertRaisesRegex(RuntimeError, "SOURCE_DRIFT_REQUIRES_CANNOT_CONFIRM"):
            f.adapter.terminalize(claim, f.terminal(claim))
        f.adapter.terminalize(claim, f.terminal(claim, status="CANNOT_CONFIRM"))
        drift = f.events()[-1]["deterministic_metrics"]["source_drift"]["files"]
        self.assertEqual(drift[0]["category"], "metadata_files")
        self.assertEqual(drift[0]["name"], "native_reference")


if __name__ == "__main__":
    unittest.main()
