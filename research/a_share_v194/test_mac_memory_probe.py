from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import long_training_adapter as adapter
import mac_parallel_canary194 as canary


def _mock_runtime_counters(monkeypatch, *, sysconf, vm_stat_result):
    monkeypatch.setattr(adapter.sys, "platform", "darwin")
    monkeypatch.setattr(adapter.platform, "platform", lambda: "macOS-test")
    monkeypatch.setattr(adapter.platform, "node", lambda: "test-host")
    monkeypatch.setattr(
        adapter.resource,
        "getrusage",
        lambda _who: SimpleNamespace(ru_maxrss=1024, ru_utime=0.1, ru_stime=0.2),
    )
    monkeypatch.setattr(adapter.os, "sysconf", sysconf)
    monkeypatch.setattr(adapter.subprocess, "run", lambda *args, **kwargs: vm_stat_result)


def test_mac_runtime_snapshot_uses_vm_stat_free_and_inactive_only(monkeypatch):
    def sysconf(name):
        if name == "SC_PHYS_PAGES":
            return 1000
        if name == "SC_PAGE_SIZE":
            return 4096
        if name == "SC_AVPHYS_PAGES":
            raise ValueError("unrecognized configuration name")
        raise AssertionError(name)

    vm_stat = SimpleNamespace(
        stdout=(
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages free: 100.\n"
            "Pages inactive: 200.\n"
            "Pages speculative: 30.\n"
            "Pages purgeable: 50.\n"
        )
    )
    _mock_runtime_counters(monkeypatch, sysconf=sysconf, vm_stat_result=vm_stat)

    snapshot = adapter.runtime_snapshot()

    assert snapshot["available_memory_bytes"] == 300 * 4096
    assert snapshot["available_memory_source"] == "MAC_VM_STAT_FREE_PLUS_INACTIVE"
    assert snapshot["available_memory_error"] is None
    assert snapshot["available_memory_page_size_bytes"] == 4096
    assert snapshot["physical_memory_bytes"] == 1000 * 4096


def test_mac_runtime_snapshot_keeps_unmeasurable_memory_fail_closed(monkeypatch):
    def sysconf(name):
        if name == "SC_PHYS_PAGES":
            return 1000
        if name == "SC_PAGE_SIZE":
            return 4096
        raise ValueError("unrecognized configuration name")

    _mock_runtime_counters(
        monkeypatch,
        sysconf=sysconf,
        vm_stat_result=SimpleNamespace(stdout="unrecognized output\n"),
    )

    snapshot = adapter.runtime_snapshot()
    selection = adapter.select_safe_fit_workers(
        requested_workers=8,
        threads_per_worker=1,
        total_thread_budget=12,
        canary_peak_rss_bytes=1000,
        available_memory_bytes=snapshot["available_memory_bytes"],
    )

    assert snapshot["available_memory_bytes"] is None
    assert snapshot["available_memory_source"] == "UNAVAILABLE"
    assert snapshot["available_memory_error"] == "VM_STAT_PAGE_SIZE_UNPARSEABLE"
    assert selection["actual_workers"] == 1
    assert selection["selection_reason"] == "AVAILABLE_MEMORY_UNMEASURABLE_SERIAL_FALLBACK"


def test_mac_runtime_snapshot_rejects_available_memory_above_physical(monkeypatch):
    def sysconf(name):
        if name == "SC_PHYS_PAGES":
            return 1000
        if name == "SC_PAGE_SIZE":
            return 4096
        if name == "SC_AVPHYS_PAGES":
            return 1200
        raise AssertionError(name)

    _mock_runtime_counters(
        monkeypatch,
        sysconf=sysconf,
        vm_stat_result=SimpleNamespace(stdout="unused"),
    )

    snapshot = adapter.runtime_snapshot()

    assert snapshot["available_memory_bytes"] is None
    assert snapshot["available_memory_source"] == "UNAVAILABLE"
    assert snapshot["available_memory_error"] == "AVAILABLE_MEMORY_EXCEEDS_PHYSICAL_MEMORY"


def test_real_fit_rss_remains_the_worker_guard_input():
    selection = adapter.select_safe_fit_workers(
        requested_workers=8,
        threads_per_worker=1,
        total_thread_budget=12,
        canary_peak_rss_bytes=13_572_096_655,
        available_memory_bytes=70 * 1024**3,
        memory_safety_fraction=0.5,
    )

    assert selection["actual_workers"] == 2
    assert selection["effective_threads"] == 2
    assert selection["memory_cap_workers"] == 2
    with pytest.raises(ValueError, match="FIT_CANARY_EXCEEDS_MEMORY_SAFETY_HEADROOM"):
        adapter.select_safe_fit_workers(
            requested_workers=8,
            threads_per_worker=1,
            total_thread_budget=12,
            canary_peak_rss_bytes=13_572_096_655,
            available_memory_bytes=20 * 1024**3,
            memory_safety_fraction=0.5,
        )


def _write_canonical_json(path, value):
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _frozen_config_files(tmp_path):
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    rss_source_path = tmp_path / "prior_canary_terminal.json"
    rss_source = {
        "exit_status": "SUCCESS",
        "run_stage": "canary",
        "runtime": {"process_peak_rss_bytes": 12_637_552_640},
    }
    _write_canonical_json(rss_source_path, rss_source)
    input_path = probe_dir / "workload.json"
    workload = {
        "kind": "deterministic_dense_float32_matrix_multiply_shards",
        "seed": 194,
        "matrix_size": 768,
        "repeats": 30,
        "input_source": "generated_per_shard_from_seed_no_external_market_data",
    }
    _write_canonical_json(input_path, workload)
    config = {
        "schema_version": "a_share_v194.mac_parallel_canary_config.v1",
        "execution_id": "unit-test-execution-194",
        "input_path": str(input_path),
        "input_sha256": adapter.sha256_file(input_path),
        "output_path": str(probe_dir / "receipt.json"),
        "fit_canary_peak_rss_bytes": 12_637_552_640,
        "fit_canary_peak_rss_source_path": str(rss_source_path),
        "fit_canary_peak_rss_source_sha256": adapter.sha256_file(rss_source_path),
        "calibration_combinations": [[1, 1], [1, 6], [1, 3]],
        "requested_combinations": [[2, 6], [4, 3], [8, 1]],
        "memory_safety_fraction": 0.5,
        "total_thread_budget": 12,
        "system_sample_interval_seconds": 0.5,
        "workload": workload,
    }
    config_path = probe_dir / "config.json"
    _write_canonical_json(config_path, config)
    return probe_dir, input_path, config_path


def test_canary_config_and_input_paths_are_sha_bound(tmp_path):
    _probe_dir, input_path, config_path = _frozen_config_files(tmp_path)
    config_sha256 = adapter.sha256_file(config_path)

    config, actual_config_sha256, input_sha256 = canary._load_frozen_config(config_path, config_sha256)

    assert actual_config_sha256 == config_sha256
    assert input_sha256 == adapter.sha256_file(input_path)
    assert config["input_sha256"] == input_sha256

    with pytest.raises(ValueError, match="CANARY_CONFIG_SHA_MISMATCH"):
        canary._load_frozen_config(config_path, "0" * 64)


def test_canary_config_fails_closed_if_workload_input_changes(tmp_path):
    _probe_dir, input_path, config_path = _frozen_config_files(tmp_path)
    config_sha256 = adapter.sha256_file(config_path)
    input_path.write_bytes(input_path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="CANARY_INPUT_SHA_MISMATCH"):
        canary._load_frozen_config(config_path, config_sha256)


def test_canary_config_fails_closed_if_real_fit_rss_source_changes(tmp_path):
    _probe_dir, _input_path, config_path = _frozen_config_files(tmp_path)
    config = adapter.load_json(config_path)
    rss_source_path = Path(config["fit_canary_peak_rss_source_path"])
    config_sha256 = adapter.sha256_file(config_path)
    rss_source_path.write_bytes(rss_source_path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="CANARY_FIT_RSS_SOURCE_SHA_MISMATCH"):
        canary._load_frozen_config(config_path, config_sha256)


def _mac_vm_stat_sysconf(name):
    if name == "SC_PHYS_PAGES":
        return 1000
    if name == "SC_PAGE_SIZE":
        return 4096
    if name == "SC_AVPHYS_PAGES":
        raise ValueError("unrecognized configuration name")
    raise AssertionError(name)


def _assert_unmeasurable_falls_back_to_serial(snapshot):
    assert snapshot["available_memory_bytes"] is None
    assert snapshot["available_memory_source"] == "UNAVAILABLE"
    selection = adapter.select_safe_fit_workers(
        requested_workers=8,
        threads_per_worker=1,
        total_thread_budget=12,
        canary_peak_rss_bytes=1000,
        available_memory_bytes=snapshot["available_memory_bytes"],
    )
    assert selection["actual_workers"] == 1
    assert selection["selection_reason"] == "AVAILABLE_MEMORY_UNMEASURABLE_SERIAL_FALLBACK"


@pytest.mark.parametrize(
    ("vm_stat_text", "expected_error"),
    [
        (
            "Mach Virtual Memory Statistics: (page size of 0 bytes)\nPages free: 1.\nPages inactive: 1.\n",
            "VM_STAT_PAGE_SIZE_INVALID",
        ),
        (
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 0.\nPages inactive: 0.\n",
            "VM_STAT_AVAILABLE_MEMORY_NONPOSITIVE",
        ),
        (
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: invalid\nPages inactive: 5.\n",
            "VM_STAT_PAGES_FREE_UNPARSEABLE",
        ),
        (
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 5.\n",
            "VM_STAT_PAGES_INACTIVE_UNPARSEABLE",
        ),
    ],
)
def test_mac_vm_stat_fallback_bad_page_values_fail_closed(monkeypatch, vm_stat_text, expected_error):
    _mock_runtime_counters(
        monkeypatch,
        sysconf=_mac_vm_stat_sysconf,
        vm_stat_result=SimpleNamespace(stdout=vm_stat_text),
    )

    snapshot = adapter.runtime_snapshot()

    assert snapshot["available_memory_error"] == expected_error
    _assert_unmeasurable_falls_back_to_serial(snapshot)


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (OSError("vm_stat missing"), "VM_STAT_OSError"),
        (
            subprocess.CalledProcessError(1, "/usr/bin/vm_stat"),
            "VM_STAT_CalledProcessError",
        ),
        (subprocess.TimeoutExpired("/usr/bin/vm_stat", 2), "VM_STAT_TimeoutExpired"),
    ],
)
def test_mac_vm_stat_fallback_command_failures_fail_closed(monkeypatch, failure, expected_error):
    _mock_runtime_counters(
        monkeypatch,
        sysconf=_mac_vm_stat_sysconf,
        vm_stat_result=SimpleNamespace(stdout="unused"),
    )

    def fail_vm_stat(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(adapter.subprocess, "run", fail_vm_stat)
    snapshot = adapter.runtime_snapshot()

    assert snapshot["available_memory_error"] == expected_error
    _assert_unmeasurable_falls_back_to_serial(snapshot)


def test_mac_vm_stat_fallback_rejects_free_plus_inactive_above_physical(monkeypatch):
    vm_stat = SimpleNamespace(
        stdout=(
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages free: 600.\n"
            "Pages inactive: 600.\n"
        )
    )
    _mock_runtime_counters(monkeypatch, sysconf=_mac_vm_stat_sysconf, vm_stat_result=vm_stat)

    snapshot = adapter.runtime_snapshot()

    assert snapshot["available_memory_error"] == "AVAILABLE_MEMORY_EXCEEDS_PHYSICAL_MEMORY"
    _assert_unmeasurable_falls_back_to_serial(snapshot)


def _stage_summary_fixture(requested_workers, selected_workers, actual_workers, threads_per_worker):
    results = [
        {
            "shard_id": index,
            "pid": 1000 + index,
            "started_monotonic_ns": 100,
            "finished_monotonic_ns": 200,
            "native_thread_pools": [{"num_threads": threads_per_worker}],
            "user_cpu_seconds": 0.1,
            "system_cpu_seconds": 0.0,
            "process_peak_rss_bytes": 1024,
            "checksum": float(index + 1),
            "checksum_finite": True,
        }
        for index in range(actual_workers)
    ]
    samples = [
        {
            "logical_cpu_count": 18,
            "physical_memory_bytes": 128 * 1024**3,
            "available_memory_bytes": 70 * 1024**3,
            "available_memory_page_size_bytes": 16384,
            "swap_used_bytes": 0,
            "load_average_1m_5m_15m": [1.0, 1.0, 1.0],
        }
    ]
    return canary._stage_summary(
        stage_id=f"cpu_{requested_workers}x{threads_per_worker}",
        requested_workers=requested_workers,
        threads_per_worker=threads_per_worker,
        total_thread_budget=12,
        numeric_selection={"actual_workers": selected_workers},
        model_selection=None,
        model_selection_error=None,
        results=results,
        samples=samples,
    )


@pytest.mark.parametrize(
    ("requested_workers", "selected_workers", "threads_per_worker"),
    [(4, 3, 3), (8, 7, 1)],
)
def test_guard_limited_worker_request_cannot_pass(
    requested_workers, selected_workers, threads_per_worker,
):
    stage = _stage_summary_fixture(
        requested_workers, selected_workers, selected_workers, threads_per_worker
    )

    assert stage["status"] == "LIMITED"
    assert stage["pass"] is False
    assert stage["requested_selection_actual_match"] is False
    assert stage["requested_workers"] > stage["selected_workers"] == stage["actual_workers"]
    assert stage["max_overlapping_workers"] == stage["actual_workers"]
    assert stage["native_threads_match"] is True
    assert stage["native_thread_budget_respected"] is True
    assert stage["stop_reason"] == "REQUESTED_WORKERS_LIMITED_BY_GUARD"


@pytest.mark.parametrize(("workers", "threads"), [(2, 6), (8, 1)])
def test_full_requested_worker_combinations_can_pass(workers, threads):
    stage = _stage_summary_fixture(workers, workers, workers, threads)

    assert stage["status"] == "PASS"
    assert stage["pass"] is True
    assert stage["requested_selection_actual_match"] is True
    assert stage["effective_native_threads_observed_upper_bound"] == workers * threads <= 12


def test_native_cpu_delta_counts_new_helpers_and_ignores_idle_threads():
    assert canary._thread_cpu_deltas({11: 100, 12: 50}, {11: 120, 12: 50, 13: 9}) == {11: 20, 13: 9}


@pytest.mark.parametrize(("before", "after", "reason"), [
    ({11: 100}, {}, "DISAPPEARED"),
    ({11: 100}, {11: 99}, "REGRESSED"),
])
def test_native_cpu_delta_fails_closed(before, after, reason):
    with pytest.raises(RuntimeError, match=reason):
        canary._thread_cpu_deltas(before, after)


def test_native_observation_missing_for_one_worker_cannot_pass(monkeypatch):
    original = canary._stage_summary
    def remove_one_pool(**kwargs):
        kwargs["results"][0]["native_thread_pools"] = []
        return original(**kwargs)
    monkeypatch.setattr(canary, "_stage_summary", remove_one_pool)
    stage = _stage_summary_fixture(2, 2, 2, 6)
    assert stage["pass"] is False
    assert stage["native_observation_complete"] is False


@pytest.mark.parametrize(("count", "valid", "passes"), [(6, True, True), (1, True, False), (6, False, False)])
def test_native_mach_observation_requires_actual_exact_count(monkeypatch, count, valid, passes):
    original = canary._stage_summary
    def add_observations(**kwargs):
        for result in kwargs["results"]:
            result["native_thread_pools"] = []
            result["native_thread_observation"] = {"active_cpu_thread_count": count, "measurement_valid": valid}
        return original(**kwargs)
    monkeypatch.setattr(canary, "_stage_summary", add_observations)
    stage = _stage_summary_fixture(2, 2, 2, 6)
    assert stage["pass"] is passes
    assert stage["native_threads_match"] is passes


def test_r3_trainer_path_reads_mode_without_sdk_override(monkeypatch):
    calls = []
    def forbidden_setter(_mode):
        calls.append(_mode)
        raise AssertionError("trainer path must not call the canary SDK setter")
    def getter():
        return 0
    fake_lib = SimpleNamespace(BLASSetThreading=forbidden_setter, BLASGetThreading=getter)
    fake_numpy = SimpleNamespace(__config__=SimpleNamespace(CONFIG={"Build Dependencies": {"blas": {"name": "accelerate"}}}))
    monkeypatch.setattr(canary.sys, "platform", "darwin")
    monkeypatch.setattr(canary.ctypes, "CDLL", lambda _path: fake_lib)
    monkeypatch.setattr(canary, "_WORKER_THREADS", 1)
    monkeypatch.setattr(canary, "_WORKER_CONTROL_PATH", "TRAINER_CONTROL_PATH")
    control = canary._configure_accelerate(fake_numpy)
    assert calls == []
    assert control["set_status"] is None
    assert control["canary_sdk_override_applied"] is False
    assert control["thread_local_mode_readback"] == 0
    assert control["mode_semantics"] == "automatic_thread_count"
    assert control["mode_is_not_a_thread_count"] is True


def test_r3_initializer_uses_existing_trainer_control(monkeypatch):
    calls = []
    def configure(**kwargs):
        calls.append(kwargs)
        return {"configuration_only": kwargs}
    monkeypatch.setattr(canary.adapter, "configure_native_thread_budget", configure)
    for name, value in [("_WORKER_CONTROL_PATH", "CANARY_ACCELERATE_API"), ("_WORKER_THREAD_CONTROL", None), ("_WORKER_BARRIER", None), ("_WORKER_THREADS", None)]:
        monkeypatch.setattr(canary, name, value)
    barrier = object()
    canary._initialize_worker(1, 12, barrier, "TRAINER_CONTROL_PATH")
    assert calls == [{"processes": 1, "threads_per_process": 1, "total_thread_budget": 12}]
    assert canary._WORKER_THREAD_CONTROL == {"configuration_only": calls[0]}
    assert canary._WORKER_CONTROL_PATH == "TRAINER_CONTROL_PATH"
    assert canary._WORKER_BARRIER is barrier


def _r3_frozen_config_files(tmp_path):
    _probe, _input, path = _frozen_config_files(tmp_path)
    config = adapter.load_json(path)
    config.update(schema_version="a_share_v194.mac_parallel_canary_config.v2", native_control_path="TRAINER_CONTROL_PATH", calibration_combinations=[[1, 1]], requested_combinations=[[2, 1], [4, 1], [8, 1], [12, 1]])
    _write_canonical_json(path, config)
    return path


def test_r3_protocol_accepts_twelve_single_workers_without_widening_v1(tmp_path):
    path = _r3_frozen_config_files(tmp_path)
    config, _sha, _input_sha = canary._load_frozen_config(path, adapter.sha256_file(path))
    assert config["calibration_combinations"] == [[1, 1]]
    assert config["requested_combinations"][-1] == [12, 1]
    with pytest.raises(canary.argparse.ArgumentTypeError):
        canary._parse_combinations("12x1")
    assert canary._parse_combinations("12x1", max_workers=12) == [(12, 1)]


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("calibration_combinations", [[1, 1], [1, 6], [1, 3]], "CALIBRATION_COMBINATIONS_INVALID"),
    ("requested_combinations", [[2, 6], [4, 1], [8, 1], [12, 1]], "TRAINER_PARALLEL_COMBINATIONS_INVALID"),
])
def test_r3_protocol_rejects_sdk_calibration_or_multithread_rescue(tmp_path, field, value, reason):
    path = _r3_frozen_config_files(tmp_path)
    config = adapter.load_json(path)
    config[field] = value
    _write_canonical_json(path, config)
    with pytest.raises(ValueError, match=reason):
        canary._load_frozen_config(path, adapter.sha256_file(path))


def _r5_config_files(tmp_path):
    _probe, _input, path = _frozen_config_files(tmp_path)
    config = adapter.load_json(path)
    for name in ("fit_canary_peak_rss_bytes", "fit_canary_peak_rss_source_path", "fit_canary_peak_rss_source_sha256"):
        config.pop(name)
    config.update(schema_version="a_share_v194.mac_parallel_canary_config.v4", native_control_path="TRAINER_CONTROL_PATH", calibration_combinations=[[1, 1]], requested_combinations=[[2, 1], [4, 1], [8, 1], [12, 1]])
    source = tmp_path / "numeric_r2_calibration.json"
    calibration = {"config": {"workload": config["workload"]}, "input_sha256": config["input_sha256"],
        "max_numeric_worker_peak_rss_bytes_observed": 52_314_112,
        "stages": [{"stage_id": "native_calibration_1x1", "pass": True,
            "observed_native_thread_counts": [1], "max_single_process_peak_rss_bytes": 52_314_112}]}
    _write_canonical_json(source, calibration)
    config.update(numeric_canary_peak_rss_bytes=52_314_112, numeric_canary_peak_rss_source_path=str(source), numeric_canary_peak_rss_source_sha256=adapter.sha256_file(source))
    _write_canonical_json(path, config)
    return path, config, source, calibration


def _r5_args(path, config):
    workload = config["workload"]
    return SimpleNamespace(config=config, config_path=path, config_sha256=adapter.sha256_file(path),
        execution_id=config["execution_id"], input_sha256=config["input_sha256"],
        seed=workload["seed"], matrix_size=workload["matrix_size"], repeats=workload["repeats"],
        fit_canary_peak_rss_bytes=None, memory_safety_fraction=0.5, total_thread_budget=12,
        sample_interval_seconds=0.5, combinations=[tuple(pair) for pair in config["requested_combinations"]])


def test_r5_cpu_profile_binding_has_no_model_receipt_dependency(tmp_path):
    path, config, source, calibration = _r5_config_files(tmp_path)
    # Removing the old model receipt proves the CPU-only loader never opens it.
    (tmp_path / "prior_canary_terminal.json").unlink()
    loaded, _sha, _input_sha = canary._load_frozen_config(path, adapter.sha256_file(path))
    assert all(not key.startswith("fit_canary") for key in loaded)
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ValueError, match="NUMERIC_RSS_SOURCE_SHA_MISMATCH"):
        canary._load_frozen_config(path, adapter.sha256_file(path))
    calibration["config"]["workload"] = dict(config["workload"], seed=195)
    _write_canonical_json(source, calibration)
    config["numeric_canary_peak_rss_source_sha256"] = adapter.sha256_file(source)
    _write_canonical_json(path, config)
    with pytest.raises(ValueError, match="NUMERIC_RSS_CALIBRATION_BINDING_INVALID"):
        canary._load_frozen_config(path, adapter.sha256_file(path))


def test_r5_cpu_own_memory_guard_stops_before_workers(monkeypatch, tmp_path):
    path, config, _source, _calibration = _r5_config_files(tmp_path)
    monkeypatch.setattr(canary, "_system_snapshot", lambda: {"available_memory_bytes": 90_000_000})
    monkeypatch.setattr(canary.adapter, "runtime_snapshot", lambda: {"pid": 123})
    def forbidden_pool(**_kwargs):
        raise AssertionError("unsafe CPU worker must not start")
    monkeypatch.setattr(canary, "_run_cpu_pool", forbidden_pool)
    receipt = canary.run_canary(_r5_args(path, config))
    assert receipt["exit_status"] == "CANNOT_CONFIRM"
    assert receipt["stop_reason"] == "NUMERIC_RESOURCE_GUARD_REJECTED:FIT_CANARY_EXCEEDS_MEMORY_SAFETY_HEADROOM"
    assert receipt["stages"] == []
    assert receipt["model_objects_created"] == receipt["model_fits"] == 0
    assert receipt["model_evaluation"] == "NOT_RUN"
    assert "safe_fit_workers" not in receipt


def test_r5_cpu_path_uses_only_cpu_budget_and_neutral_terminal(monkeypatch, tmp_path):
    path, config, _source, _calibration = _r5_config_files(tmp_path)
    sample = {"available_memory_bytes": 20_459_536_384, "physical_memory_bytes": 137_438_953_472,
        "logical_cpu_count": 18, "available_memory_page_size_bytes": 16384,
        "swap_used_bytes": 0, "load_average_1m_5m_15m": [5.0, 5.0, 5.0]}
    monkeypatch.setattr(canary, "_system_snapshot", lambda: dict(sample))
    monkeypatch.setattr(canary.adapter, "runtime_snapshot", lambda: {"pid": 123})
    calls = []
    original_selector = canary._select_workers
    def cpu_selector(**kwargs):
        calls.append(kwargs)
        assert kwargs["canary_peak_rss_bytes"] == 52_314_112
        return original_selector(**kwargs)
    monkeypatch.setattr(canary, "_select_workers", cpu_selector)
    class Monitor:
        def __init__(self, _interval):
            self.samples = [dict(sample)]
        def __enter__(self):
            return self
        def __exit__(self, *_exc):
            return False
    monkeypatch.setattr(canary, "_SystemMonitor", Monitor)
    def cpu_pool(**kwargs):
        assert kwargs["native_control_path"] == "TRAINER_CONTROL_PATH"
        return [{"pid": 1000 + index, "shard_id": index, "started_monotonic_ns": 1000,
            "finished_monotonic_ns": 2000, "user_cpu_seconds": 0.1, "system_cpu_seconds": 0.0,
            "process_peak_rss_bytes": 52_314_112, "native_thread_pools": [],
            "native_thread_observation": {"active_cpu_thread_count": 1, "measurement_valid": True},
            "checksum_finite": True} for index in range(kwargs["workers"])]
    monkeypatch.setattr(canary, "_run_cpu_pool", cpu_pool)
    receipt = canary.run_canary(_r5_args(path, config))
    assert calls
    assert receipt["exit_status"] == "SUCCESS"
    assert receipt["engineering_status"] == "CPU_PARALLEL_PASS_MODEL_NOT_RUN"
    assert receipt["stage_pass_count"] == 5
    assert receipt["model_objects_created"] == receipt["model_fits"] == 0
    assert receipt["model_evaluation"] == "NOT_RUN"
    assert "safe_fit_workers" not in receipt and "model_fit_preview" not in receipt
    assert "model_fit_selection_using_real_canary_rss_baseline" not in receipt
    assert all("model_fit_selection_using_real_canary_rss" not in stage for stage in receipt["stages"])
