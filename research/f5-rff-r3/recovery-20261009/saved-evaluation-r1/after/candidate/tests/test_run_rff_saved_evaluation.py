"""Synthetic saved-file/official-registry integration; monitor substitution is explicit.

Uses the actual worker, accepted join, frozen evaluator and official append chain.
Only the Mac runtime/evaluator import roots and process monitor are substituted.
All scores, labels, registry history and receipts are generated in temp folders.
"""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import rff_saved_eval_contracts as common
import test_rff_saved_eval_registration as registry_fixture
import test_rff_saved_eval_worker as worker_fixture


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        worker_fixture.SavedWorkerTest.setUpClass()

    @classmethod
    def tearDownClass(cls):
        worker_fixture.SavedWorkerTest.tearDownClass()

    def setUp(self):
        path = SRC / "run_rff_saved_evaluation.py"
        self.assertTrue(path.is_file(), "saved-evaluation lifecycle launcher is missing")
        self.runner = worker_fixture.load(path, "synthetic_rff_runner")
        self.w = worker_fixture.SavedWorkerTest()
        self.w.setUp()
        self.addCleanup(self.w.doCleanups)
        registration = registry_fixture.load(SRC / "rff_saved_eval_registration.py", "synthetic_runner_registration")
        self.f = registry_fixture.SyntheticOfficialRegistry(registration)
        self.addCleanup(self.f.close)
        self.resources = {"cpu_threads": 4, "aggregate_process_tree_rss_bytes_max": 2147483648,
                          "wall_seconds_max": 60, "sample_seconds": 0.05}
        old_spec = json.loads(Path(self.w.binding["run_spec_path"]).read_bytes())
        spec = {**old_spec, "execution_id": registry_fixture.EXECUTION,
                "resources": self.resources, "synthetic_only": True}
        registry_fixture.write_json(self.f.run_spec_path, spec)
        registry_keys = ("official_helpers", "official_registry_path", "official_registry_sha256_before_start",
                         "expected_previous_event_sha256", "expected_route_event_sha256_before_start", "start_receipt_path")
        b = {**self.w.binding, **{key: self.f.binding[key] for key in registry_keys},
             "execution_id": registry_fixture.EXECUTION, "output_root": str(self.f.start_receipt_path.parent),
             "run_spec_path": str(self.f.run_spec_path), "input_binding_path": str(self.f.binding_path),
             "run_spec_sha256": common.sha256_file(self.f.run_spec_path), "resources": self.resources,
             "candidate_output_root": str(self.w.root / "SYNTHETIC_OLD_CANDIDATE"),
             "resource_trace_path": str(self.f.root / "evidence" / "resource.json"),
             "executable_helpers": {"native_runtime": common.file_record(self.f.worker_source),
                "resource_tree": common.file_record(registry_fixture.ROOT / "inputs/attachments/xendcg_saved_eval/helpers/resource_tree.py")}}
        self.f.binding = b
        self.f.rebuild()
        self.binding = self.f.binding
        self.output = Path(b["output_root"])
        self.monitor_calls = 0
        self.monitor_mode = "success"

    def monitor(self, target, payload, **kwargs):
        self.monitor_calls += 1
        self.assertIsNone(target)
        self.assertEqual(kwargs["target_descriptor"]["callable"], "run_saved_evaluation")
        if self.monitor_mode == "raise_before_observation":
            raise RuntimeError("SYNTHETIC_UNKNOWN_MONITOR_CRASH")
        if self.monitor_mode in {"proven_no_spawn", "contradictory_no_spawn", "legacy_no_spawn_only"}:
            common.write_json_exclusive(kwargs["failure_evidence_path"], {
                "exit_code_state": "PROCESS_NOT_STARTED", "stage": "SPAWN_START",
                "target_descriptor": kwargs["target_descriptor"],
                "source_files": {**kwargs["failure_context"]["source_files"],
                                 "resource_tree": self.binding["executable_helpers"]["resource_tree"]}})
            error = RuntimeError("SYNTHETIC_SPAWN_FAILED")
            if self.monitor_mode != "legacy_no_spawn_only":
                started = self.monitor_mode == "contradictory_no_spawn"
                abort = {**kwargs["failure_context"], "schema": "F5_RFF_SAVED_EVAL_MONITOR_ABORT_V1",
                    "status": "MONITOR_ABORT", "stage": "UNEXPECTED_MONITOR_EXCEPTION",
                    "target_descriptor": kwargs["target_descriptor"],
                    "resource_trace_path": str(kwargs["resource_trace_path"]),
                    "source_files": {**kwargs["failure_context"]["source_files"],
                                     "resource_tree": self.binding["executable_helpers"]["resource_tree"]},
                    "process_creation_count": 1, "process_start_attempted_count": int(started),
                    "process_start_returned_count": int(started), "process_tree_termination_confirmed": True,
                    "exit_code_state": "JOINED_AFTER_ABORT_CLEANUP" if started else "PROCESS_NOT_STARTED",
                    "workers": [{"pid": 12345 if started else None,
                        "process_state": "EXIT_CONFIRMED_AFTER_ABORT_CLEANUP" if started else "PROCESS_NOT_STARTED",
                        "process_start_attempted": started, "process_start_returned": started}]}
                # The contradictory case intentionally has no file: a failed
                # abort write must not erase the parent's in-memory evidence.
                error.rff_monitor_abort = abort
                if not started:
                    common.write_json_exclusive(self.output / "EVALUATION_MONITOR_ABORT.json", abort)
            raise error
        exitcode = 0
        try:
            self.w.worker.run_saved_evaluation(payload)
        except Exception:
            exitcode = 1
        if self.monitor_mode == "crash_after_marker":
            for name in ("EVALUATION_WORKER_STATUS.json", "EVALUATION_RESULT_RECEIPT.json", "METRICS.json"):
                (self.output / name).unlink(missing_ok=True)
            exitcode = 9
        if self.monitor_mode == "native_status_mismatch":
            path = self.output / "EVALUATION_WORKER_STATUS.json"
            status = json.loads(path.read_bytes())
            status["native_runtime_checks_completed"] = 0
            registry_fixture.write_json(path, status)
        if self.monitor_mode == "wrong_metrics_source":
            path = self.output / "METRICS.json"
            metrics = json.loads(path.read_bytes())
            metrics["source_code_sha256"] = "f" * 64
            registry_fixture.write_json(path, metrics)
            result_path = self.output / "EVALUATION_RESULT_RECEIPT.json"
            result = json.loads(result_path.read_bytes())
            result["metrics_sha256"] = common.sha256_file(path)
            registry_fixture.write_json(result_path, result)
            status_path = self.output / "EVALUATION_WORKER_STATUS.json"
            status = json.loads(status_path.read_bytes())
            status["metrics_sha256"] = result["metrics_sha256"]
            status["result_receipt_sha256"] = common.sha256_file(result_path)
            registry_fixture.write_json(status_path, status)
        result = {"synthetic_monitor_substitution": True, "worker_exitcode": exitcode,
            "terminal_reason": None, "threads": kwargs["threads"],
            "wall_seconds_max": kwargs["wall_seconds_max"],
            "aggregate_rss_bytes_max": kwargs["rss_bytes_max"],
            "elapsed_seconds": 0.1, "peak_aggregate_tree_rss_bytes": 1024,
            "post_trace_fsync_terminal_check": {"after_trace_fsync": True},
            "final_post_fsync_check": {"after_final_trace_fsync": True}, "samples": []}
        if self.monitor_mode == "missing_final_check":
            result.pop("final_post_fsync_check")
        common.write_json_exclusive(kwargs["resource_trace_path"], result)
        return result

    def execute(self):
        return self.runner._execute_bound(binding=self.binding, input_binding_sha256=self.f.binding_sha,
            adapter=self.f.adapter, guard=self.f.guard, guard_module=self.f.guard_module,
            native_spec={"synthetic_only": True, "dyld_library_path": ""},
            native_observation={"synthetic_runtime_substitution": True}, monitor=self.monitor)

    def receipt(self):
        return json.loads((self.output / "EVALUATION_RUN_RECEIPT.json").read_bytes())

    def assert_closed_once(self, decision):
        new = self.f.events()[646:]
        self.assertEqual([row["event_type"] for row in new], ["RUN_STARTED", "TERMINAL"])
        self.assertEqual(new[-1]["decision"], decision)
        self.assertTrue(self.f.registry_path.read_bytes().startswith(self.f.before))
        self.assertEqual(self.f.guard.accounting().real_fit_budget_debit_count, 1)
        terminal = json.loads((self.output / "EVALUATION_TERMINAL_RECEIPT.json").read_bytes())
        self.assertEqual(terminal["terminal_event_sha256"], new[-1]["event_sha256"])
        self.assertEqual(terminal["run_receipt_sha256"], common.sha256_file(self.output / "EVALUATION_RUN_RECEIPT.json"))

    def test_full_saved_file_lifecycle_preserves_old_fit_and_closes_once(self):
        before = {k: common.sha256_file(Path(v["path"])) for k, v in self.w.inputs.items()}
        result = self.execute()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(self.monitor_calls, 1)
        self.assert_closed_once("COMPLETED")
        receipt = self.receipt()
        self.assertEqual(receipt["observed_worker_accounting"]["status"], "KNOWN")
        self.assertEqual(receipt["truth_accounting"]["evaluation_truth_decode_attempts"], 1)
        self.assertEqual(receipt["truth_accounting"]["evaluation_truth_decodes_completed"], 1)
        self.assertEqual(receipt["evaluation_metrics"]["evidence_ceiling"], "DIRECTION_ONLY")
        self.assertEqual(before, {k: common.sha256_file(Path(v["path"])) for k, v in self.w.inputs.items()})

    def test_resource_profile_mismatch_is_rejected_before_start(self):
        self.binding["resources"]["cpu_threads"] = 8
        self.f.rebuild()
        with self.assertRaisesRegex(Exception, "MONITOR.*THREAD"):
            self.execute()
        self.assertEqual(self.f.registry_path.read_bytes(), self.f.before)
        self.assertEqual(self.monitor_calls, 0)
        self.assertFalse(self.output.exists())

    def test_preexisting_output_rejects_before_start_and_keeps_bytes(self):
        self.output.mkdir(parents=True)
        (self.output / "KEEP").write_bytes(b"synthetic preserved output")
        with self.assertRaisesRegex(Exception, "REENTRY"):
            self.execute()
        self.assertEqual(self.f.registry_path.read_bytes(), self.f.before)
        self.assertEqual((self.output / "KEEP").read_bytes(), b"synthetic preserved output")

    def test_second_invocation_cannot_append_or_reread_truth(self):
        self.execute()
        before = self.f.registry_path.read_bytes()
        with self.assertRaisesRegex(Exception, "REENTRY"):
            self.execute()
        self.assertEqual(self.f.registry_path.read_bytes(), before)
        self.assertEqual(self.monitor_calls, 1)

    def test_parse_failure_records_attempt_one_completion_zero(self):
        original = self.w.worker._read_csv
        def broken(raw, *, name, columns):
            if name == "eval_truth":
                raise ValueError("SYNTHETIC_TRUTH_PARSE_FAILURE")
            return original(raw, name=name, columns=columns)
        with mock.patch.object(self.w.worker, "_read_csv", side_effect=broken):
            result = self.execute()
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["truth_accounting"]["evaluation_truth_decode_attempts"], 1)
        self.assertEqual(self.receipt()["truth_accounting"]["evaluation_truth_decodes_completed"], 0)

    def test_missing_status_preserves_marker_and_reports_unknown_completion(self):
        self.monitor_mode = "crash_after_marker"
        result = self.execute()
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "UNKNOWN")
        truth = self.receipt()["truth_accounting"]
        self.assertEqual(truth["evaluation_truth_decode_attempts"], 1)
        self.assertIsNone(truth["evaluation_truth_decodes_completed"])

    def test_monitor_exception_without_spawn_proof_does_not_invent_zero(self):
        self.monitor_mode = "raise_before_observation"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "UNKNOWN")
        self.assertIsNone(self.receipt()["truth_accounting"]["evaluation_truth_decode_attempts"])

    def test_explicit_process_not_started_proof_records_known_zero(self):
        self.monitor_mode = "proven_no_spawn"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "KNOWN_NOT_LAUNCHED")
        self.assertEqual(self.receipt()["truth_accounting"]["evaluation_truth_decode_attempts"], 0)

    def test_abort_actual_start_vetoes_legacy_process_not_started_marker(self):
        self.monitor_mode = "contradictory_no_spawn"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "UNKNOWN")
        self.assertIsNone(self.receipt()["truth_accounting"]["evaluation_truth_decode_attempts"])
        self.assertEqual(self.receipt()["error"]["monitor_abort"]["workers"][0]["pid"], 12345)

    def test_legacy_no_spawn_marker_alone_cannot_prove_zero_activity(self):
        self.monitor_mode = "legacy_no_spawn_only"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "UNKNOWN")

    def test_worker_exit_zero_without_final_fsync_check_is_not_completed(self):
        self.monitor_mode = "missing_final_check"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertFalse(self.receipt()["evaluation_metrics"]["metrics_computed"])

    def test_completed_receipts_require_child_native_check_and_matching_source(self):
        self.monitor_mode = "native_status_mismatch"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")

    def test_rehashed_metrics_cannot_claim_different_source_code_identity(self):
        self.monitor_mode = "wrong_metrics_source"
        self.execute()
        self.assert_closed_once("CANNOT_CONFIRM")

    def test_start_append_raised_after_durable_is_read_back_then_closed_without_worker(self):
        original = self.f.adapter._append_unlocked
        attempts = []
        def raised_after(raw, events, spec):
            attempts.append(spec["event_type"])
            original(raw, events, spec)
            if spec["event_type"] == "RUN_STARTED":
                raise OSError("SYNTHETIC_RAISED_AFTER_START_FSYNC")
        with mock.patch.object(self.f.adapter, "_append_unlocked", side_effect=raised_after):
            result = self.execute()
        self.assertEqual(attempts, ["RUN_STARTED", "TERMINAL"])
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertEqual(self.monitor_calls, 0)
        self.assert_closed_once("CANNOT_CONFIRM")
        self.assertEqual(self.receipt()["observed_worker_accounting"]["status"], "KNOWN_NOT_LAUNCHED")

    def test_start_append_failure_before_durable_is_not_retried_or_terminalized(self):
        with mock.patch.object(self.f.adapter, "_append_unlocked", side_effect=OSError("SYNTHETIC_APPEND_DENIED")) as append:
            with self.assertRaisesRegex(Exception, "SYNTHETIC_APPEND_DENIED"):
                self.execute()
        self.assertEqual(append.call_count, 1)
        self.assertEqual(self.monitor_calls, 0)
        self.assertEqual(self.f.registry_path.read_bytes(), self.f.before)

    def test_terminal_append_raised_after_durable_is_read_back_without_retry(self):
        original = self.f.adapter._append_unlocked
        attempts = []
        def raised_after(raw, events, spec):
            attempts.append(spec["event_type"])
            original(raw, events, spec)
            if spec["event_type"] == "TERMINAL":
                raise OSError("SYNTHETIC_RAISED_AFTER_TERMINAL_FSYNC")
        with mock.patch.object(self.f.adapter, "_append_unlocked", side_effect=raised_after):
            result = self.execute()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(attempts, ["RUN_STARTED", "TERMINAL"])
        self.assert_closed_once("COMPLETED")
        self.assertTrue(result["terminal_append_raised_after_durable"])

    def test_unprovable_terminal_failure_reports_dangling_start_without_retry(self):
        original = self.f.adapter._append_unlocked
        attempts = []
        def broken(raw, events, spec):
            attempts.append(spec["event_type"])
            if spec["event_type"] == "TERMINAL":
                raise OSError("SYNTHETIC_TERMINAL_APPEND_DENIED")
            return original(raw, events, spec)
        with mock.patch.object(self.f.adapter, "_append_unlocked", side_effect=broken):
            with self.assertRaisesRegex(Exception, "TERMINALIZATION_UNCONFIRMED"):
                self.execute()
        self.assertEqual(attempts, ["RUN_STARTED", "TERMINAL"])
        self.assertEqual([e["event_type"] for e in self.f.events()[646:]], ["RUN_STARTED"])
        self.assertTrue((self.output / "TERMINALIZATION_BLOCKED.json").is_file())
        self.assertFalse((self.output / "EVALUATION_TERMINAL_RECEIPT.json").exists())

    def test_start_receipt_write_failure_still_attempts_failure_terminal(self):
        c = self.runner._common()
        original = c.write_json_exclusive
        def broken(path, value):
            if Path(path).name == "EVALUATION_START_RECEIPT.json":
                raise OSError("SYNTHETIC_START_RECEIPT_WRITE_FAILED")
            return original(path, value)
        with mock.patch.object(c, "write_json_exclusive", side_effect=broken):
            result = self.execute()
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertEqual(self.monitor_calls, 0)
        self.assert_closed_once("CANNOT_CONFIRM")

    def test_run_receipt_write_failure_still_attempts_failure_terminal(self):
        self.monitor_mode = "proven_no_spawn"
        c = self.runner._common()
        original = c.write_json_exclusive
        def broken(path, value):
            if Path(path).name == "EVALUATION_RUN_RECEIPT.json":
                raise OSError("SYNTHETIC_RUN_RECEIPT_WRITE_FAILED")
            return original(path, value)
        with mock.patch.object(c, "write_json_exclusive", side_effect=broken):
            result = self.execute()
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertEqual([row["event_type"] for row in self.f.events()[646:]], ["RUN_STARTED", "TERMINAL"])
        self.assertIsNone(result["run_receipt_sha256"])
        self.assertIn("SYNTHETIC_RUN_RECEIPT_WRITE_FAILED", result["run_receipt_error"]["message"])

    def test_optional_evidence_stat_error_cannot_skip_failure_terminal(self):
        self.monitor_mode = "proven_no_spawn"
        original = Path.exists
        raised = False
        def denied(path):
            nonlocal raised
            if path == self.output / "METRICS.json" and not raised:
                raised = True
                raise PermissionError("SYNTHETIC_EVIDENCE_STAT_DENIED")
            return original(path)
        with mock.patch.object(Path, "exists", denied):
            result = self.execute()
        self.assertTrue(raised)
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assert_closed_once("CANNOT_CONFIRM")


if __name__ == "__main__":
    unittest.main()
