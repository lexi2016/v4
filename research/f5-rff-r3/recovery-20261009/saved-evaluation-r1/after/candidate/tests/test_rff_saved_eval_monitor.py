"""Real spawn of generated no-data targets through the original resource helper.

The native helper, worker target and RSS rows are synthetic. This container's
ps PID namespace differs from Python's, so a fixture supplies rows for only this
test's real multiprocessing children. Spawn, child liveness, signals, join and
the original monitor/termination functions execute. This does not validate the
Mac OS measurement backend. No real data, registry or model is opened.
"""
from __future__ import annotations

import hashlib
import contextlib
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MONITOR_PATH = ROOT / "inputs/attachments/xendcg_saved_eval/helpers/resource_tree.py"
ADAPTER_PATH = ROOT / "candidate/src/run_rff_saved_evaluation.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MonitorWrapperTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER_PATH.is_file(), "route monitor-abort adapter is missing")
        self.adapter = load(ADAPTER_PATH, "synthetic_monitor_abort_adapter")
        self.old_monitor = sys.modules.get("resource_tree")
        self.old_path = list(sys.path)
        sys.path.insert(0, str(MONITOR_PATH.parent))
        self.monitor = load(MONITOR_PATH, "resource_tree")
        self.addCleanup(self.restore_imports)
        self.initial_children = {p.pid for p in mp.active_children()}
        self.temp = tempfile.TemporaryDirectory(prefix="rff-saved-monitor-test-")
        self.addCleanup(self.temp.cleanup)
        snapshot_patch = mock.patch.object(self.monitor, "_ps_process_snapshot",
                                          side_effect=self.synthetic_process_snapshot)
        snapshot_patch.start()
        self.addCleanup(snapshot_patch.stop)
        backend_patch = mock.patch.object(self.monitor, "_load_psutil", return_value=None)
        backend_patch.start()
        self.addCleanup(backend_patch.stop)
        # Runs before either snapshot patch is stopped or temp files disappear.
        self.addCleanup(self.cleanup_children)
        self.root = Path(self.temp.name).resolve()
        self.native = self.root / "synthetic_native.py"
        self.native.write_text(
            "import contextlib\n"
            "def validate_native_files(spec, **kwargs):\n"
            "    if spec.get('reject_native'):\n"
            "        raise ValueError('SYNTHETIC_NATIVE_REJECTED')\n"
            "    return {'synthetic_only': True}\n"
            "def process_local_dyld_for_spawn(value):\n"
            "    return contextlib.nullcontext()\n")
        self.target = self.root / "synthetic_target.py"
        self.target.write_text(
            "import time\n"
            "from pathlib import Path\n"
            "def run_saved_evaluation(payload):\n"
            "    Path(payload['started']).write_text('synthetic-started')\n"
            "    time.sleep(payload['seconds'])\n"
            "    Path(payload['finished']).write_text('synthetic-finished')\n")
        self.payload = {"synthetic_only": True, "seconds": 0.0,
            "started": str(self.root / "started.txt"), "finished": str(self.root / "finished.txt")}
        self.descriptor = {"path": str(self.target),
            "sha256": hashlib.sha256(self.target.read_bytes()).hexdigest(),
            "module_name": "synthetic_monitor_target", "callable": "run_saved_evaluation"}
        self.kwargs = {"native_spec": {"synthetic_only": True, "dyld_library_path": ""},
            "native_runtime_helper_path": self.native, "wall_seconds_max": 15,
            "rss_bytes_max": 2147483648, "threads": 4, "sample_seconds": 0.01,
            "resource_trace_path": self.root / "trace.json", "target_descriptor": self.descriptor,
            "failure_evidence_path": self.root / "EVALUATION_MONITOR_FAILURE.json",
            "failure_context": {"execution_id": "SYNTHETIC_MONITOR_REVIEW",
                "source_files": {"synthetic_target": {"path": str(self.target), "sha256": self.descriptor["sha256"]}}}}
        self.real_cleanup = self.monitor._safe_terminate_descendants

    def synthetic_process_snapshot(self):
        # Synthetic RSS values; actual Process liveness and exact namespace IDs.
        parent = os.getpid()
        rows = {parent: {"pid": parent, "ppid": os.getppid(), "rss_bytes": 1024,
                         "status": "S"}}
        for process in mp.active_children():
            if process.pid not in self.initial_children and process.is_alive():
                rows[process.pid] = {"pid": process.pid, "ppid": parent,
                                     "rss_bytes": 1024, "status": "S"}
        return rows

    def restore_imports(self):
        sys.path[:] = self.old_path
        if self.old_monitor is None:
            sys.modules.pop("resource_tree", None)
        else:
            sys.modules["resource_tree"] = self.old_monitor

    def cleanup_children(self):
        # A deliberately injected cleanup failure is isolated to its test;
        # the test harness still cleans any synthetic child in finally.
        for process in mp.active_children():
            if process.pid not in self.initial_children:
                self.real_cleanup(process, {})
                if process.exitcode is not None:
                    process.close()

    def run_monitor(self):
        return self.adapter._monitor_once(self.monitor, None, self.payload, **self.kwargs)

    def abort(self):
        return json.loads((self.root / "EVALUATION_MONITOR_ABORT.json").read_bytes())

    def assert_no_new_children(self):
        self.assertEqual([p.pid for p in mp.active_children() if p.pid not in self.initial_children], [])

    def cleanup_fault_injected_handles(self, launched):
        # An emergency test-harness cleanup does not satisfy an assertion that
        # the wrapper itself already closed a child before it returned.
        for process, popen in launched:
            if popen.poll() is None:
                process._popen = popen
                process._sentinel = popen.sentinel
                self.real_cleanup(process, {})
                self.assertFalse(process.is_alive())
                if process.exitcode is not None:
                    process.close()

    def test_real_spawn_normal_completion_has_no_extra_cleanup(self):
        original_mp = self.monitor.mp
        original_sample = self.monitor._tree_rss_bytes
        with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
            result = self.run_monitor()
        self.assertEqual(result["worker_exitcode"], 0)
        self.assertIsNone(result["terminal_reason"])
        self.assertTrue(Path(self.payload["finished"]).is_file())
        self.assertEqual(cleanup.call_count, 0)
        self.assertFalse((self.root / "EVALUATION_MONITOR_ABORT.json").exists())
        self.assertIs(self.monitor.mp, original_mp)
        self.assertIs(self.monitor._tree_rss_bytes, original_sample)
        self.assert_no_new_children()

    def test_keyboard_interrupt_cleans_spawned_worker_once_and_preserves_error(self):
        self.payload["seconds"] = 10
        error = KeyboardInterrupt("SYNTHETIC_MONITOR_INTERRUPT")
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=error):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(cleanup.call_count, 1)
        record = self.abort()
        self.assertEqual(record["exception_type"], "KeyboardInterrupt")
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assertEqual(record["process_creation_count"], 1)
        self.assertEqual(record["target_descriptor"], self.descriptor)
        self.assertEqual(record["workers"][0]["process_state"], "EXIT_CONFIRMED_AFTER_ABORT_CLEANUP")
        self.assert_no_new_children()

    def test_trace_write_failure_after_worker_exit_still_preserves_failure_evidence(self):
        error = OSError("SYNTHETIC_TRACE_WRITE_DENIED")
        with mock.patch.object(self.monitor, "_write_json_fsync", side_effect=error):
            with self.assertRaises(OSError) as caught:
                self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertTrue(self.abort()["process_tree_termination_confirmed"])
        self.assertEqual(self.abort()["exception_message"], str(error))
        self.assert_no_new_children()

    def test_native_failure_before_process_creation_never_attempts_cleanup(self):
        self.kwargs["native_spec"]["reject_native"] = True
        with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
            with self.assertRaisesRegex(ValueError, "SYNTHETIC_NATIVE_REJECTED"):
                self.run_monitor()
        self.assertEqual(cleanup.call_count, 0)
        record = self.abort()
        self.assertEqual(record["process_creation_count"], 0)
        self.assertEqual(record["exit_code_state"], "PROCESS_NOT_STARTED")
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assert_no_new_children()

    def test_context_exit_error_after_real_spawn_overrides_old_not_started_claim(self):
        self.payload["seconds"] = 10
        error = OSError("SYNTHETIC_CONTEXT_EXIT_AFTER_SPAWN")
        @contextlib.contextmanager
        def broken_exit(_threads):
            yield
            raise error
        with mock.patch.object(self.monitor, "_thread_limits_for_spawn", side_effect=broken_exit):
            with self.assertRaises(OSError) as caught:
                self.run_monitor()
        self.assertIs(caught.exception, error)
        old_failure = json.loads(self.kwargs["failure_evidence_path"].read_bytes())
        self.assertEqual(old_failure["exit_code_state"], "PROCESS_NOT_STARTED")
        record = self.abort()
        self.assertIsInstance(record["workers"][0]["pid"], int)
        self.assertTrue(record["workers"][0]["process_start_attempted"])
        self.assertTrue(record["workers"][0]["process_start_returned"])
        self.assertEqual(record["exit_code_state"], "JOINED_AFTER_ABORT_CLEANUP")
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assert_no_new_children()

    def test_partial_popen_exception_is_reclaimed_and_cleaned_by_wrapper(self):
        self.payload["seconds"] = 10
        spawn_class = mp.get_context("spawn").Process
        real_popen = spawn_class._Popen
        launched = []
        error = OSError("SYNTHETIC_AFTER_POPEN_BEFORE_PROCESS_ASSIGNMENT")
        def started_then_failed(process):
            popen = real_popen(process)
            launched.append((process, popen))
            raise error
        self.addCleanup(self.cleanup_fault_injected_handles, launched)
        with mock.patch.object(spawn_class, "_Popen", side_effect=started_then_failed):
            with self.assertRaises(OSError) as caught:
                self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0][1].poll(), "wrapper left the real partial-start child alive")
        record = self.abort()
        self.assertEqual(record["workers"][0]["pid"], launched[0][1].pid)
        self.assertTrue(record["workers"][0]["process_start_attempted"])
        self.assertFalse(record["workers"][0]["process_start_returned"])
        self.assertTrue(record["workers"][0]["popen_handle_recovered"])
        self.assertEqual(record["process_start_attempted_count"], 1)
        self.assertEqual(record["process_start_returned_count"], 0)
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assertEqual(record["exit_code_state"], "JOINED_AFTER_ABORT_CLEANUP")

    def test_popen_constructor_exception_after_spawn_recovers_preobserved_handle(self):
        from multiprocessing import popen_spawn_posix
        self.payload["seconds"] = 10
        original_init = popen_spawn_posix.Popen.__init__
        launched = []
        error = OSError("SYNTHETIC_POPEN_INIT_EXCEPTION_AFTER_REAL_SPAWN")
        def broken_constructor(popen, process):
            original_init(popen, process)
            launched.append((process, popen))
            raise error
        self.addCleanup(self.cleanup_fault_injected_handles, launched)
        with mock.patch.object(popen_spawn_posix.Popen, "__init__", new=broken_constructor):
            with self.assertRaises(OSError) as caught:
                self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0][1].poll(), "constructor fault left a real child alive")
        record = self.abort()
        self.assertTrue(record["workers"][0]["popen_handle_recovered"])
        self.assertEqual(record["workers"][0]["popen_instances_observed"], 1)
        self.assertFalse(record["workers"][0]["process_start_returned"])
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assertIs(popen_spawn_posix.Popen.__init__, original_init)

    def test_sigint_before_baseprocess_handle_assignment_is_deferred_then_cleaned(self):
        from multiprocessing import popen_spawn_posix
        self.payload["seconds"] = 10
        spawn_class = mp.get_context("spawn").Process
        real_popen = spawn_class._Popen
        original_init = popen_spawn_posix.Popen.__init__
        original_sigint = signal.getsignal(signal.SIGINT)
        launched = []
        def interrupt_before_assignment(process):
            popen = real_popen(process)
            launched.append((process, popen))
            os.kill(os.getpid(), signal.SIGINT)
            return popen
        self.addCleanup(self.cleanup_fault_injected_handles, launched)
        with mock.patch.object(spawn_class, "_Popen", side_effect=interrupt_before_assignment):
            with self.assertRaises(KeyboardInterrupt):
                self.run_monitor()
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0][1].poll(), "deferred SIGINT left a real child alive")
        record = self.abort()
        self.assertEqual(record["workers"][0]["sigint_deferred_during_start"], 1)
        self.assertTrue(record["workers"][0]["process_start_attempted"])
        self.assertTrue(record["workers"][0]["process_start_returned"])
        self.assertFalse(record["workers"][0]["popen_handle_recovered"])
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assertIs(popen_spawn_posix.Popen.__init__, original_init)
        self.assertIs(signal.getsignal(signal.SIGINT), original_sigint)
        self.assert_no_new_children()

    def test_start_failure_without_a_popen_instance_cannot_invent_a_handle(self):
        from multiprocessing import popen_spawn_posix
        spawn_class = mp.get_context("spawn").Process
        original_init = popen_spawn_posix.Popen.__init__
        original_sigint = signal.getsignal(signal.SIGINT)
        error = OSError("SYNTHETIC_BEFORE_POPEN_CONSTRUCTION")
        with mock.patch.object(spawn_class, "_Popen", side_effect=error):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
                with self.assertRaises(OSError) as caught:
                    self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(cleanup.call_count, 0)
        record = self.abort()
        self.assertEqual(record["workers"][0]["popen_instances_observed"], 0)
        self.assertFalse(record["workers"][0]["popen_handle_recovered"])
        self.assertIsNone(record["workers"][0]["pid"])
        self.assertFalse(record["process_tree_termination_confirmed"])
        self.assertIs(popen_spawn_posix.Popen.__init__, original_init)
        self.assertIs(signal.getsignal(signal.SIGINT), original_sigint)
        self.assert_no_new_children()

    def test_context_enter_failure_proves_process_start_was_not_attempted(self):
        @contextlib.contextmanager
        def broken_enter(_threads):
            raise OSError("SYNTHETIC_CONTEXT_ENTER_BEFORE_START")
            yield
        with mock.patch.object(self.monitor, "_thread_limits_for_spawn", side_effect=broken_enter):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
                with self.assertRaisesRegex(OSError, "BEFORE_START"):
                    self.run_monitor()
        self.assertEqual(cleanup.call_count, 0)
        record = self.abort()
        self.assertEqual(record["process_creation_count"], 1)
        self.assertFalse(record["workers"][0]["process_start_attempted"])
        self.assertFalse(record["workers"][0]["process_start_returned"])
        self.assertEqual(record["exit_code_state"], "PROCESS_NOT_STARTED")
        self.assertTrue(record["process_tree_termination_confirmed"])
        self.assert_no_new_children()

    def test_last_successful_tree_snapshot_survives_the_next_sample_interrupt(self):
        self.payload["seconds"] = 10
        real_sample = self.monitor._tree_rss_bytes
        retained = {}
        def sample_then_interrupt(*args, **kwargs):
            if retained:
                raise KeyboardInterrupt("SYNTHETIC_INTERRUPT_AFTER_KNOWN_TREE")
            result = real_sample(*args, **kwargs)
            retained.update(result[2])
            return result
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=sample_then_interrupt):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
                with self.assertRaisesRegex(KeyboardInterrupt, "AFTER_KNOWN_TREE"):
                    self.run_monitor()
        self.assertTrue(retained)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(set(cleanup.call_args.args[1]), set(retained))
        self.assertTrue(self.abort()["process_tree_termination_confirmed"])
        self.assert_no_new_children()

    def test_original_resource_breach_returns_without_adapter_cleanup_retry(self):
        self.payload["seconds"] = 10
        real_sample = self.monitor._tree_rss_bytes
        calls = 0
        def breach_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            rss, members, retained = real_sample(*args, **kwargs)
            return (self.kwargs["rss_bytes_max"] + 1 if calls == 1 else rss), members, retained
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=breach_once):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", wraps=self.real_cleanup) as cleanup:
                result = self.run_monitor()
        self.assertTrue(result["terminal_reason"].startswith("RSS_LIMIT_EXCEEDED"))
        self.assertGreater(cleanup.call_count, 0)
        self.assertFalse((self.root / "EVALUATION_MONITOR_ABORT.json").exists())
        self.assert_no_new_children()

    def test_cleanup_exception_is_recorded_unknown_without_replacing_primary_error(self):
        self.payload["seconds"] = 10
        error = KeyboardInterrupt("SYNTHETIC_PRIMARY_INTERRUPT")
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=error):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants",
                                   side_effect=KeyboardInterrupt("SYNTHETIC_CLEANUP_INTERRUPT")) as cleanup:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(cleanup.call_count, 1)
        record = self.abort()
        self.assertFalse(record["process_tree_termination_confirmed"])
        self.assertEqual(record["workers"][0]["cleanup_error"]["type"], "KeyboardInterrupt")
        self.assertEqual(record["exit_code_state"], "CANNOT_CONFIRM")

    def test_repeated_sigint_during_cleanup_is_deferred_and_recorded(self):
        self.payload["seconds"] = 10
        error = KeyboardInterrupt("SYNTHETIC_PRIMARY_INTERRUPT")
        original_signal_handler = signal.getsignal(signal.SIGINT)
        def repeat_interrupt(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGINT)
            return self.real_cleanup(*args, **kwargs)
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=error):
            with mock.patch.object(self.monitor, "_safe_terminate_descendants", side_effect=repeat_interrupt):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.abort()["sigint_deferred_during_cleanup"], 1)
        self.assertTrue(self.abort()["process_tree_termination_confirmed"])
        self.assertIs(signal.getsignal(signal.SIGINT), original_signal_handler)
        self.assert_no_new_children()

    def test_abort_evidence_write_failure_retains_primary_and_in_memory_evidence(self):
        self.payload["seconds"] = 10
        error = KeyboardInterrupt("SYNTHETIC_PRIMARY_INTERRUPT")
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=error):
            with mock.patch.object(self.monitor, "write_failure_evidence_atomic",
                                   side_effect=OSError("SYNTHETIC_ABORT_WRITE_DENIED")):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.run_monitor()
        self.assertIs(caught.exception, error)
        self.assertTrue(error.rff_monitor_abort["process_tree_termination_confirmed"])
        self.assertEqual(error.rff_monitor_abort["abort_evidence_write_error"]["type"], "OSError")
        self.assert_no_new_children()

    def test_backend_preflight_samples_parent_once_without_spawning(self):
        with mock.patch.object(self.monitor, "_tree_rss_bytes", wraps=self.monitor._tree_rss_bytes) as sample:
            with mock.patch.object(self.monitor.mp, "get_context", side_effect=AssertionError("preflight spawned")):
                result = self.adapter._check_monitor_backend(self.monitor,
                    {"aggregate_process_tree_rss_bytes_max": 1024})
        sample.assert_called_once_with(os.getpid(), None, {})
        self.assertEqual(result["backend"], "posix_ps")
        self.assertEqual(result["aggregate_process_tree_rss_bytes"], 1024)
        self.assertEqual(result["process_ids"], [os.getpid()])
        self.assertEqual(result["scope"], "CALLER_ONLY_BEFORE_RUN_STARTED")
        self.assertFalse(self.kwargs["resource_trace_path"].exists())
        self.assert_no_new_children()

    def test_backend_preflight_failure_keeps_the_original_observation_error(self):
        error = OSError("SYNTHETIC_OS_RSS_BACKEND_UNAVAILABLE")
        with mock.patch.object(self.monitor, "_tree_rss_bytes", side_effect=error) as sample:
            with self.assertRaisesRegex(RuntimeError, "MONITOR_BACKEND_PREFLIGHT_FAILED") as caught:
                self.adapter._check_monitor_backend(self.monitor,
                    {"aggregate_process_tree_rss_bytes_max": 1024})
        self.assertIs(caught.exception.__cause__, error)
        sample.assert_called_once_with(os.getpid(), None, {})
        self.assert_no_new_children()

    def test_backend_preflight_rejects_nonpositive_or_nonnumeric_rss(self):
        for value in (0, -1, True, None):
            with self.subTest(rss=value):
                with mock.patch.object(self.monitor, "_tree_rss_bytes",
                                       return_value=(value, [os.getpid()], {})) as sample:
                    with self.assertRaisesRegex(RuntimeError, "MONITOR_BACKEND_PREFLIGHT_FAILED"):
                        self.adapter._check_monitor_backend(self.monitor,
                            {"aggregate_process_tree_rss_bytes_max": 1024})
                sample.assert_called_once_with(os.getpid(), None, {})
        self.assert_no_new_children()

    def test_backend_preflight_rejects_already_exceeded_explicit_cap(self):
        with mock.patch.object(self.monitor, "_tree_rss_bytes",
                               return_value=(1025, [os.getpid()], {})) as sample:
            with self.assertRaisesRegex(RuntimeError, "RESOURCE_RSS_ALREADY_EXCEEDS_BOUND"):
                self.adapter._check_monitor_backend(self.monitor,
                    {"aggregate_process_tree_rss_bytes_max": 1024})
        sample.assert_called_once_with(os.getpid(), None, {})
        self.assert_no_new_children()


if __name__ == "__main__":
    unittest.main()
