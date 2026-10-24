"""Registered, deterministic CPU-only canary for the V194 Mac runtime path.

This validates spawned process overlap and native BLAS thread settings. It does
not load V194 data, fit a model, create predictions, or produce OOF outputs.
"""
from __future__ import annotations

import argparse
import ctypes
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import threading
import time
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import long_training_adapter as adapter


SAFETY_FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_WORKER_BARRIER: Any = None
_WORKER_THREADS: int | None = None
_WORKER_CONTROL_PATH = "CANARY_ACCELERATE_API"
_WORKER_THREAD_CONTROL: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bytes_for_ru_maxrss(value: int) -> int:
    return int(value) if sys.platform == "darwin" else int(value) * 1024


def _initialize_worker(
    threads_per_worker: int, total_thread_budget: int, barrier: Any,
    native_control_path: str = "CANARY_ACCELERATE_API",
) -> None:
    global _WORKER_BARRIER, _WORKER_THREADS, _WORKER_CONTROL_PATH, _WORKER_THREAD_CONTROL
    if native_control_path not in ("CANARY_ACCELERATE_API", "TRAINER_CONTROL_PATH"):
        raise ValueError("NATIVE_CONTROL_PATH_INVALID")
    _WORKER_THREAD_CONTROL = adapter.configure_native_thread_budget(
        processes=1,
        threads_per_process=threads_per_worker,
        total_thread_budget=total_thread_budget,
    )
    _WORKER_BARRIER = barrier
    _WORKER_THREADS = threads_per_worker
    _WORKER_CONTROL_PATH = native_control_path


class _DarwinThreadObserver:
    """Read only this task's Mach thread CPU counters; release every send right.

    THREAD_BASIC_INFO and THREAD_IDENTIFIER_INFO layouts come from the installed
    macOS SDK mach/thread_info.h. No task_for_pid or foreign-process access.
    """
    def __init__(self) -> None:
        self.lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        self.task = ctypes.c_uint.in_dll(self.lib, "mach_task_self_").value
        uint = ctypes.c_uint
        self.lib.task_threads.argtypes = [uint, ctypes.POINTER(ctypes.POINTER(uint)), ctypes.POINTER(uint)]
        self.lib.task_threads.restype = ctypes.c_int
        self.lib.thread_info.argtypes = [uint, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(uint)]
        self.lib.thread_info.restype = ctypes.c_int
        self.lib.mach_port_deallocate.argtypes = [uint, uint]
        self.lib.mach_port_deallocate.restype = ctypes.c_int
        self.lib.vm_deallocate.argtypes = [uint, ctypes.c_uint64, ctypes.c_uint64]
        self.lib.vm_deallocate.restype = ctypes.c_int

    def snapshot(self) -> dict[int, int]:
        ports = ctypes.POINTER(ctypes.c_uint)()
        count = ctypes.c_uint()
        if self.lib.task_threads(self.task, ctypes.byref(ports), ctypes.byref(count)) != 0:
            raise RuntimeError("MACH_TASK_THREADS_FAILED")
        result: dict[int, int] = {}
        try:
            for index in range(count.value):
                basic = (ctypes.c_int * 10)()
                basic_count = ctypes.c_uint(10)
                identifier = (ctypes.c_uint64 * 3)()
                identifier_count = ctypes.c_uint(6)
                if (self.lib.thread_info(ports[index], 3, basic, ctypes.byref(basic_count)) != 0
                    or self.lib.thread_info(ports[index], 4, identifier, ctypes.byref(identifier_count)) != 0
                    or basic_count.value != 10 or identifier_count.value != 6):
                    raise RuntimeError("MACH_THREAD_INFO_FAILED")
                cpu_us = (int(basic[0]) + int(basic[2])) * 1_000_000 + int(basic[1]) + int(basic[3])
                result[int(identifier[0])] = cpu_us
        finally:
            errors = [self.lib.mach_port_deallocate(self.task, ports[index]) for index in range(count.value)]
            errors.append(self.lib.vm_deallocate(
                self.task, ctypes.cast(ports, ctypes.c_void_p).value, count.value * ctypes.sizeof(ctypes.c_uint)
            ))
            if any(errors):
                raise RuntimeError("MACH_THREAD_RIGHT_RELEASE_FAILED")
        if not result:
            raise RuntimeError("MACH_THREAD_SNAPSHOT_EMPTY")
        return result


def _thread_cpu_deltas(before: dict[int, int], after: dict[int, int]) -> dict[int, int]:
    # New persistent BLAS helper threads have consumed all their CPU since birth.
    # A disappearing thread prevents a complete bound and must fail closed.
    if set(before) - set(after):
        raise RuntimeError("MACH_THREAD_DISAPPEARED_DURING_MATMUL")
    deltas = {key: value - before.get(key, 0) for key, value in after.items()}
    if any(value < 0 for value in deltas.values()):
        raise RuntimeError("MACH_THREAD_CPU_COUNTER_REGRESSED")
    return {key: value for key, value in deltas.items() if value > 0}


def _configure_accelerate(np: Any) -> dict[str, Any] | None:
    if sys.platform != "darwin" or np.__config__.CONFIG.get("Build Dependencies", {}).get("blas", {}).get("name") != "accelerate":
        return None
    lib = ctypes.CDLL("/System/Library/Frameworks/Accelerate.framework/Accelerate")
    lib.BLASSetThreading.argtypes = [ctypes.c_uint]
    lib.BLASSetThreading.restype = ctypes.c_int
    lib.BLASGetThreading.argtypes = []
    lib.BLASGetThreading.restype = ctypes.c_uint
    sdk_override = _WORKER_CONTROL_PATH == "CANARY_ACCELERATE_API"
    mode = 1 if _WORKER_THREADS == 1 else 0
    status = lib.BLASSetThreading(mode) if sdk_override else None
    readback = int(lib.BLASGetThreading())
    if readback not in (0, 1) or (sdk_override and (status != 0 or readback != mode)):
        raise RuntimeError("ACCELERATE_THREAD_MODE_READBACK_FAILED")
    return {
        "blas_vendor": "Apple Accelerate", "set_status": status,
        "control_path": _WORKER_CONTROL_PATH,
        "canary_sdk_override_applied": sdk_override,
        "thread_local_mode_readback": readback,
        "mode_semantics": "single_threaded" if readback == 1 else "automatic_thread_count",
        "mode_is_not_a_thread_count": True,
        "veclib_maximum_threads_environment": os.environ.get("VECLIB_MAXIMUM_THREADS"),
    }


def _numeric_cpu_shard(
    shard_id: int, *, size: int, repeats: int, seed: int,
) -> dict[str, Any]:
    """Run deterministic dense numeric work after all spawned workers are ready."""
    import numpy as np
    from threadpoolctl import threadpool_info

    accelerate_control = _configure_accelerate(np)
    observer = _DarwinThreadObserver() if accelerate_control is not None else None
    thread_cpu_deltas: dict[int, int] = {}
    matmul_thread_samples = []
    rng = np.random.default_rng(seed + shard_id)
    left = rng.standard_normal((size, size), dtype=np.float32)
    right = np.roll(left, shift=(shard_id % size, (shard_id * 7) % size), axis=(0, 1)).copy()
    _WORKER_BARRIER.wait(timeout=45.0)
    started_ns = time.monotonic_ns()
    started_at = _utc_now()
    before_cpu = resource.getrusage(resource.RUSAGE_SELF)
    checksum = 0.0
    for index in range(repeats):
        threads_before = observer.snapshot() if observer is not None else None
        product = left @ right
        if observer is not None:
            threads_after = observer.snapshot()
            deltas = _thread_cpu_deltas(threads_before, threads_after)
            matmul_thread_samples.append({"iteration": index, "active_cpu_thread_ids": sorted(deltas)})
            for thread_id, cpu_us in deltas.items():
                thread_cpu_deltas[thread_id] = thread_cpu_deltas.get(thread_id, 0) + cpu_us
        checksum += float(product[(shard_id + index) % size, (index * 17 + shard_id) % size])
        left = np.tanh(product * np.float32(0.0001 + (index % 3) * 0.00001))
    after_cpu = resource.getrusage(resource.RUSAGE_SELF)
    finished_ns = time.monotonic_ns()
    pools = [
        {
            "user_api": str(pool.get("user_api", "unknown")),
            "internal_api": str(pool.get("internal_api", "unknown")),
            "num_threads": int(pool["num_threads"]),
        }
        for pool in threadpool_info()
        if pool.get("user_api") in ("blas", "openmp") and type(pool.get("num_threads")) is int
    ]
    return {
        "shard_id": shard_id,
        "pid": os.getpid(),
        "started_at_utc": started_at,
        "started_monotonic_ns": started_ns,
        "finished_monotonic_ns": finished_ns,
        "wall_seconds": (finished_ns - started_ns) / 1_000_000_000,
        "user_cpu_seconds": float(after_cpu.ru_utime - before_cpu.ru_utime),
        "system_cpu_seconds": float(after_cpu.ru_stime - before_cpu.ru_stime),
        "process_peak_rss_bytes": _bytes_for_ru_maxrss(after_cpu.ru_maxrss),
        "native_thread_pools": pools,
        "accelerate_thread_control": accelerate_control,
        "trainer_native_thread_control": _WORKER_THREAD_CONTROL,
        "native_thread_observation": ({
            "source": "MACH_SELF_THREAD_CPU_DELTAS_AROUND_EACH_MATMUL",
            "scope": "own_worker_task_only_no_observer_thread",
            "active_cpu_thread_count": len(thread_cpu_deltas),
            "active_cpu_thread_microseconds": {str(key): value for key, value in sorted(thread_cpu_deltas.items())},
            "samples": matmul_thread_samples,
            "measurement_valid": bool(thread_cpu_deltas) and len(matmul_thread_samples) == repeats,
            "limitation": "CPU participants observed at call boundaries; not a scheduler concurrency or unsampled transient-thread guarantee",
        } if observer is not None else None),
        "checksum": checksum,
        "checksum_finite": math.isfinite(checksum),
    }


def _swap_usage_bytes() -> tuple[int | None, str | None]:
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "vm.swapusage"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"SYSCTL_SWAP_{type(exc).__name__}"
    match = re.search(r"\bused\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?)", result.stdout, re.I)
    if match is None:
        return None, "SYSCTL_SWAP_OUTPUT_UNPARSEABLE"
    scale = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    value = int(float(match.group(1)) * scale[match.group(2).upper()])
    if value < 0:
        return None, "SYSCTL_SWAP_USED_NEGATIVE"
    return value, None


def _system_snapshot() -> dict[str, Any]:
    runtime = adapter.runtime_snapshot()
    swap_bytes, swap_error = _swap_usage_bytes()
    try:
        load_average = [float(value) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load_average = None
    return {
        "sampled_at_utc": _utc_now(),
        "logical_cpu_count": runtime["logical_cpu_count"],
        "physical_memory_bytes": runtime["physical_memory_bytes"],
        "available_memory_bytes": runtime["available_memory_bytes"],
        "available_memory_page_size_bytes": runtime["available_memory_page_size_bytes"],
        "available_memory_source": runtime["available_memory_source"],
        "available_memory_error": runtime["available_memory_error"],
        "swap_used_bytes": swap_bytes,
        "swap_error": swap_error,
        "load_average_1m_5m_15m": load_average,
    }


class _SystemMonitor:
    def __init__(self, interval_seconds: float = 0.5) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.samples.append(_system_snapshot())
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "_SystemMonitor":
        self.samples.append(_system_snapshot())
        self._thread = threading.Thread(target=self._sample, name="v194-mac-canary-monitor", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds * 4))
        self.samples.append(_system_snapshot())


def _max_overlap(results: list[dict[str, Any]]) -> int:
    events: list[tuple[int, int]] = []
    for item in results:
        events.append((int(item["started_monotonic_ns"]), 1))
        events.append((int(item["finished_monotonic_ns"]), -1))
    active = 0
    maximum = 0
    for _stamp, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def _run_cpu_pool(
    *, workers: int, threads_per_worker: int, total_thread_budget: int,
    size: int, repeats: int, seed: int,
    native_control_path: str = "CANARY_ACCELERATE_API",
) -> list[dict[str, Any]]:
    adapter.configure_native_thread_budget(
        processes=workers,
        threads_per_process=threads_per_worker,
        total_thread_budget=total_thread_budget,
    )
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(workers)
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(threads_per_worker, total_thread_budget, barrier, native_control_path),
    ) as pool:
        futures = [
            pool.submit(_numeric_cpu_shard, shard, size=size, repeats=repeats, seed=seed)
            for shard in range(workers)
        ]
        return [future.result() for future in as_completed(futures)]


def _select_workers(
    *, requested_workers: int, threads_per_worker: int, total_thread_budget: int,
    canary_peak_rss_bytes: int, available_memory_bytes: int | None, safety_fraction: float,
) -> dict[str, Any]:
    return adapter.select_safe_fit_workers(
        requested_workers=requested_workers,
        threads_per_worker=threads_per_worker,
        total_thread_budget=total_thread_budget,
        canary_peak_rss_bytes=canary_peak_rss_bytes,
        available_memory_bytes=available_memory_bytes,
        memory_safety_fraction=safety_fraction,
    )


def _stage_summary(
    *, stage_id: str, requested_workers: int, threads_per_worker: int,
    total_thread_budget: int,
    numeric_selection: dict[str, Any], model_selection: dict[str, Any] | None,
    model_selection_error: str | None, results: list[dict[str, Any]],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_threads = threads_per_worker
    observed_pids = sorted({int(result["pid"]) for result in results})
    native_counts = []
    native_observation_complete = bool(results)
    for result in results:
        observation = result.get("native_thread_observation")
        if observation is not None:
            count = observation.get("active_cpu_thread_count")
            valid = observation.get("measurement_valid") is True and type(count) is int and count > 0
            native_observation_complete &= valid
            if valid:
                native_counts.append(count)
        else:
            pools = result["native_thread_pools"]
            native_observation_complete &= bool(pools)
            native_counts.extend(pool["num_threads"] for pool in pools)

    actual_workers = len(observed_pids)
    max_overlap = _max_overlap(results)
    wall_seconds = max((result["finished_monotonic_ns"] for result in results), default=0) - min(
        (result["started_monotonic_ns"] for result in results), default=0
    )
    wall_seconds /= 1_000_000_000
    cpu_seconds = sum(result["user_cpu_seconds"] + result["system_cpu_seconds"] for result in results)
    logical_cpus = next((sample.get("logical_cpu_count") for sample in samples if sample.get("logical_cpu_count")), None)
    physical_memory = next(
        (int(sample["physical_memory_bytes"]) for sample in samples if sample.get("physical_memory_bytes")),
        None,
    )
    minimum_available = min(
        (int(sample["available_memory_bytes"]) for sample in samples if sample.get("available_memory_bytes") is not None),
        default=None,
    )
    memory_probe_valid = all(
        type(sample.get("available_memory_bytes")) is int and sample["available_memory_bytes"] > 0
        for sample in samples
    )
    swap_probe_valid = all(
        type(sample.get("swap_used_bytes")) is int and sample["swap_used_bytes"] >= 0
        for sample in samples
    )
    load_probe_valid = all(
        isinstance(sample.get("load_average_1m_5m_15m"), list)
        and len(sample["load_average_1m_5m_15m"]) == 3
        and all(math.isfinite(float(value)) and float(value) >= 0 for value in sample["load_average_1m_5m_15m"])
        for sample in samples
    )
    swap_samples = [int(sample["swap_used_bytes"]) for sample in samples if sample.get("swap_used_bytes") is not None]
    load_samples = [
        float(sample["load_average_1m_5m_15m"][0])
        for sample in samples
        if sample.get("load_average_1m_5m_15m")
    ]
    selection_matches = actual_workers == numeric_selection["actual_workers"]
    request_matches_selection = numeric_selection["actual_workers"] == requested_workers
    overlap_matches = (
        max_overlap == 1 and actual_workers == 1
        if requested_workers == 1
        else max_overlap == actual_workers and actual_workers > 1
    )
    observed_native_thread_upper_bound = sum(native_counts)
    native_thread_budget_respected = observed_native_thread_upper_bound <= total_thread_budget
    native_threads_match = (
        native_observation_complete
        and bool(native_counts)
        and all(count == expected_threads for count in native_counts)
        and native_thread_budget_respected
    )
    checksums_finite = all(result["checksum_finite"] for result in results)
    passed = (
        selection_matches
        and request_matches_selection
        and overlap_matches
        and native_threads_match
        and native_thread_budget_respected
        and memory_probe_valid
        and swap_probe_valid
        and load_probe_valid
        and checksums_finite
        and len(results) == numeric_selection["actual_workers"]
    )
    guard_limited = (
        numeric_selection["actual_workers"] < requested_workers
        and selection_matches
        and overlap_matches
        and native_threads_match
        and native_thread_budget_respected
        and memory_probe_valid
        and swap_probe_valid
        and load_probe_valid
        and checksums_finite
        and len(results) == numeric_selection["actual_workers"]
    )
    stage_status = "PASS" if passed else "LIMITED" if guard_limited else "CANNOT_CONFIRM"
    return {
        "stage_id": stage_id,
        "requested_workers": requested_workers,
        "numeric_canary_selection": numeric_selection,
        "selected_workers": numeric_selection["actual_workers"],
        "actual_workers": actual_workers,
        "requested_selection_actual_match": request_matches_selection and selection_matches,
        "status": stage_status,
        "native_thread_budget_respected": native_thread_budget_respected,
        "observed_pids": observed_pids,
        "max_overlapping_workers": max_overlap,
        "threads_per_worker_requested": threads_per_worker,
        "observed_native_thread_counts": native_counts,
        "native_thread_pools": [result["native_thread_pools"] for result in results],
        "native_observation_complete": native_observation_complete,
        "native_thread_count_semantics": "observed CPU participants for Accelerate; library pool size for supported threadpoolctl backends",
        "effective_native_threads_observed_upper_bound": observed_native_thread_upper_bound,
        "native_threads_match": native_threads_match,
        "model_fit_selection_using_real_canary_rss": model_selection,
        "model_fit_selection_error": model_selection_error,
        "cpu_worker_seconds": cpu_seconds,
        "wall_seconds": wall_seconds,
        "approximate_host_cpu_capacity_percent": (
            100.0 * cpu_seconds / wall_seconds / logical_cpus
            if wall_seconds > 0 and logical_cpus else None
        ),
        "aggregate_sum_process_peak_rss_bytes": sum(int(result["process_peak_rss_bytes"]) for result in results),
        "max_single_process_peak_rss_bytes": max(
            (int(result["process_peak_rss_bytes"]) for result in results), default=0
        ),
        "system_min_available_memory_bytes": minimum_available,
        "available_memory_page_sizes_bytes": sorted({
            int(sample["available_memory_page_size_bytes"])
            for sample in samples
            if sample.get("available_memory_page_size_bytes") is not None
        }),
        "system_baseline_available_memory_bytes": next(
            (int(sample["available_memory_bytes"]) for sample in samples if sample.get("available_memory_bytes") is not None), None
        ),
        "system_memory_used_estimate_peak_bytes": (
            max(0, physical_memory - minimum_available)
            if physical_memory is not None and minimum_available is not None else None
        ),
        "system_memory_probe_valid_for_all_samples": memory_probe_valid,
        "system_swap_probe_valid_for_all_samples": swap_probe_valid,
        "system_cpu_load_probe_valid_for_all_samples": load_probe_valid,
        "system_swap_used_baseline_bytes": next(
            (int(sample["swap_used_bytes"]) for sample in samples if sample.get("swap_used_bytes") is not None), None
        ),
        "system_swap_used_peak_bytes": max(swap_samples, default=None),
        "system_load_average_baseline": next(
            (sample.get("load_average_1m_5m_15m") for sample in samples if sample.get("load_average_1m_5m_15m") is not None), None
        ),
        "system_load_average_1m_peak": max(load_samples, default=None),
        "worker_results": sorted(results, key=lambda item: item["shard_id"]),
        "pass": passed,
        "stop_reason": (
            None if passed else
            "REQUESTED_WORKERS_LIMITED_BY_GUARD" if guard_limited else
            "AVAILABLE_MEMORY_PROBE_FAILED_DURING_STAGE" if not memory_probe_valid else
            "SWAP_PROBE_FAILED_DURING_STAGE" if not swap_probe_valid else
            "CPU_LOAD_PROBE_FAILED_DURING_STAGE" if not load_probe_valid else
            "NATIVE_THREAD_COUNT_OR_BUDGET_MISMATCH" if not native_threads_match or not native_thread_budget_respected else
            "WORKER_OVERLAP_CHECK_FAILED"
        ),
    }


def _load_frozen_config(config_path: Path, expected_sha256: str) -> tuple[dict[str, Any], str, str]:
    config_path = config_path.resolve()
    actual_config_sha256 = adapter.sha256_file(config_path)
    if actual_config_sha256 != expected_sha256:
        raise ValueError("CANARY_CONFIG_SHA_MISMATCH")
    config = adapter.load_json(config_path)
    cpu_only = config.get("schema_version") == "a_share_v194.mac_parallel_canary_config.v4"
    trainer_protocol = config.get("schema_version") in (
        "a_share_v194.mac_parallel_canary_config.v2", "a_share_v194.mac_parallel_canary_config.v4"
    )
    required_keys = {
        "schema_version", "execution_id", "input_path", "input_sha256", "output_path",
        "fit_canary_peak_rss_bytes", "fit_canary_peak_rss_source_path",
        "fit_canary_peak_rss_source_sha256", "calibration_combinations", "requested_combinations",
        "memory_safety_fraction", "total_thread_budget", "system_sample_interval_seconds", "workload",
    }
    if trainer_protocol:
        required_keys.add("native_control_path")
    if cpu_only:
        required_keys.difference_update({"fit_canary_peak_rss_bytes", "fit_canary_peak_rss_source_path", "fit_canary_peak_rss_source_sha256"})
        required_keys.update({"numeric_canary_peak_rss_bytes", "numeric_canary_peak_rss_source_path", "numeric_canary_peak_rss_source_sha256"})
    if set(config) != required_keys or config.get("schema_version") not in (
        "a_share_v194.mac_parallel_canary_config.v1", "a_share_v194.mac_parallel_canary_config.v2", "a_share_v194.mac_parallel_canary_config.v4"
    ):
        raise ValueError("CANARY_CONFIG_SCHEMA_INVALID")
    if trainer_protocol and config["native_control_path"] != "TRAINER_CONTROL_PATH":
        raise ValueError("CANARY_TRAINER_CONTROL_PATH_INVALID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{8,80}", str(config["execution_id"])):
        raise ValueError("CANARY_EXECUTION_ID_INVALID")
    if not cpu_only:
        if type(config["fit_canary_peak_rss_bytes"]) is not int or config["fit_canary_peak_rss_bytes"] <= 0:
            raise ValueError("CANARY_FIT_RSS_INVALID")
        peak_source_path = Path(config["fit_canary_peak_rss_source_path"]).resolve()
        peak_source_sha256 = adapter.sha256_file(peak_source_path)
        if peak_source_sha256 != config["fit_canary_peak_rss_source_sha256"]:
            raise ValueError("CANARY_FIT_RSS_SOURCE_SHA_MISMATCH")
        peak_source = adapter.load_json(peak_source_path)
        if peak_source.get("exit_status") != "SUCCESS" or peak_source.get("run_stage") != "canary":
            raise ValueError("CANARY_FIT_RSS_SOURCE_NOT_SUCCESSFUL_CANARY")
        source_rss = peak_source.get("runtime", {}).get("process_peak_rss_bytes")
        if type(source_rss) is not int or source_rss != config["fit_canary_peak_rss_bytes"]:
            raise ValueError("CANARY_FIT_RSS_SOURCE_VALUE_MISMATCH")
    if type(config["total_thread_budget"]) is not int or config["total_thread_budget"] != 12:
        raise ValueError("CANARY_THREAD_BUDGET_INVALID")
    if type(config["memory_safety_fraction"]) not in (int, float) or not (
        0.2 <= config["memory_safety_fraction"] <= 1.0
    ):
        raise ValueError("CANARY_MEMORY_SAFETY_FRACTION_INVALID")
    if type(config["system_sample_interval_seconds"]) not in (int, float) or not (
        0.1 <= config["system_sample_interval_seconds"] <= 2.0
    ):
        raise ValueError("CANARY_SAMPLE_INTERVAL_INVALID")

    config_dir = config_path.parent
    input_path = Path(config["input_path"]).resolve()
    output_path = Path(config["output_path"]).resolve()
    if input_path.parent != config_dir or output_path.parent != config_dir:
        raise ValueError("CANARY_ARTIFACT_PATH_OUTSIDE_PROBE_DIRECTORY")
    if output_path.exists():
        raise ValueError("CANARY_OUTPUT_ALREADY_EXISTS")
    actual_input_sha256 = adapter.sha256_file(input_path)
    if actual_input_sha256 != config["input_sha256"]:
        raise ValueError("CANARY_INPUT_SHA_MISMATCH")
    workload = adapter.load_json(input_path)
    if set(workload) != {"kind", "seed", "matrix_size", "repeats", "input_source"}:
        raise ValueError("CANARY_WORKLOAD_SCHEMA_INVALID")
    if workload["kind"] != "deterministic_dense_float32_matrix_multiply_shards":
        raise ValueError("CANARY_WORKLOAD_KIND_INVALID")
    if workload["input_source"] != "generated_per_shard_from_seed_no_external_market_data":
        raise ValueError("CANARY_WORKLOAD_SOURCE_INVALID")
    if any(type(workload[name]) is not int for name in ("seed", "matrix_size", "repeats")):
        raise ValueError("CANARY_WORKLOAD_PARAMETERS_INVALID")
    if not (64 <= workload["matrix_size"] <= 1024 and 1 <= workload["repeats"] <= 60):
        raise ValueError("CANARY_WORKLOAD_OUTSIDE_BOUNDED_ENVELOPE")
    if config["workload"] != workload:
        raise ValueError("CANARY_CONFIG_WORKLOAD_DIFFERS_FROM_INPUT")
    if cpu_only:
        if config["memory_safety_fraction"] != 0.5:
            raise ValueError("CANARY_CPU_MEMORY_SAFETY_FRACTION_CHANGED")
        peak = config["numeric_canary_peak_rss_bytes"]
        if type(peak) is not int or peak <= 0:
            raise ValueError("CANARY_NUMERIC_RSS_INVALID")
        source_path = Path(config["numeric_canary_peak_rss_source_path"]).resolve()
        if adapter.sha256_file(source_path) != config["numeric_canary_peak_rss_source_sha256"]:
            raise ValueError("CANARY_NUMERIC_RSS_SOURCE_SHA_MISMATCH")
        source = adapter.load_json(source_path)
        calibration = next(iter(source.get("stages", [])), {})
        if (source.get("config", {}).get("workload") != workload
            or source.get("input_sha256") != actual_input_sha256
            or source.get("max_numeric_worker_peak_rss_bytes_observed") != peak
            or calibration.get("stage_id") != "native_calibration_1x1"
            or calibration.get("pass") is not True
            or calibration.get("observed_native_thread_counts") != [1]
            or calibration.get("max_single_process_peak_rss_bytes") != peak):
            raise ValueError("CANARY_NUMERIC_RSS_CALIBRATION_BINDING_INVALID")
    expected_calibration = [[1, 1]] if trainer_protocol else [[1, 1], [1, 6], [1, 3]]
    if config["calibration_combinations"] != expected_calibration:
        raise ValueError("CANARY_CALIBRATION_COMBINATIONS_INVALID")
    raw_combinations = config["requested_combinations"]
    if not isinstance(raw_combinations, list) or not raw_combinations:
        raise ValueError("CANARY_REQUESTED_COMBINATIONS_INVALID")
    if trainer_protocol and raw_combinations != [[2, 1], [4, 1], [8, 1], [12, 1]]:
        raise ValueError("CANARY_TRAINER_PARALLEL_COMBINATIONS_INVALID")
    try:
        combinations = _parse_combinations(
            ",".join(f"{item[0]}x{item[1]}" for item in raw_combinations),
            max_workers=12 if trainer_protocol else 8,
        )
    except (IndexError, TypeError, argparse.ArgumentTypeError) as exc:
        raise ValueError("CANARY_REQUESTED_COMBINATIONS_INVALID") from exc
    if any(workers * threads > config["total_thread_budget"] for workers, threads in combinations):
        raise ValueError("CANARY_REQUESTED_COMBINATION_EXCEEDS_THREAD_BUDGET")
    return config, actual_config_sha256, actual_input_sha256


def run_canary(args: argparse.Namespace) -> dict[str, Any]:
    cpu_only = args.config["schema_version"] == "a_share_v194.mac_parallel_canary_config.v4"
    workload = {
        "kind": "deterministic_dense_float32_matrix_multiply_shards",
        "seed": args.seed,
        "matrix_size": args.matrix_size,
        "repeats": args.repeats,
        "input_source": "generated_per_shard_from_seed_no_external_market_data",
    }
    input_sha256 = args.input_sha256
    config = {
        "execution_id": args.execution_id,
        "calibration_combinations": [(1, 1), (1, 6), (1, 3)],
        "requested_combinations": args.combinations,
        "fit_canary_peak_rss_bytes": args.fit_canary_peak_rss_bytes,
        "memory_safety_fraction": args.memory_safety_fraction,
        "total_thread_budget": args.total_thread_budget,
        "workload": workload,
        "system_sample_interval_seconds": args.sample_interval_seconds,
    }
    config = args.config
    config_sha256 = args.config_sha256
    code_sha256 = {
        "mac_parallel_canary194.py": adapter.sha256_file(__file__),
        "long_training_adapter.py": adapter.sha256_file(MODULE_DIR / "long_training_adapter.py"),
        "test_mac_memory_probe.py": adapter.sha256_file(MODULE_DIR / "test_mac_memory_probe.py"),
        "README_LONG_HISTORY.md": adapter.sha256_file(MODULE_DIR / "README_LONG_HISTORY.md"),
    }
    receipt: dict[str, Any] = {
        "schema_version": "a_share_v194.mac_parallel_canary.v1",
        "execution_id": args.execution_id,
        "started_at_utc": _utc_now(),
        "runtime": adapter.runtime_snapshot(),
        "config": config,
        "native_control_path": config.get("native_control_path", "CANARY_ACCELERATE_API"),
        "config_path": str(args.config_path),
        "config_sha256": config_sha256,
        "input_path": config["input_path"],
        "input_sha256": input_sha256,
        "code_sha256": code_sha256,
        "safety_flags": SAFETY_FLAGS,
        "model_fit_worker_guard_basis": None if cpu_only else {
            "canary_peak_rss_bytes": args.fit_canary_peak_rss_bytes,
            "source_path": config["fit_canary_peak_rss_source_path"],
            "source_sha256": config["fit_canary_peak_rss_source_sha256"],
            "source_field": "runtime.process_peak_rss_bytes",
            "memory_safety_fraction": args.memory_safety_fraction,
        },
        "mac_available_memory_method": {
            "source": "SC_AVPHYS_PAGES_when_available_else_vm_stat_free_plus_inactive",
            "vm_stat_page_size_reported_by_system": True,
            "speculative_pages_included": False,
            "purgeable_pages_included": False,
        },
        "stages": [],
        "exit_status": "RUNNING",
    }
    if cpu_only:
        receipt.pop("model_fit_worker_guard_basis")
        receipt.update({"protocol": "CPU_ONLY", "model_objects_created": 0,
                        "model_fits": 0, "model_evaluation": "NOT_RUN",
                        "numeric_worker_guard_basis": {
                            "peak_rss_bytes": config["numeric_canary_peak_rss_bytes"],
                            "source_path": config["numeric_canary_peak_rss_source_path"],
                            "source_sha256": config["numeric_canary_peak_rss_source_sha256"],
                            "source_field": "max_numeric_worker_peak_rss_bytes_observed",
                            "memory_safety_fraction": args.memory_safety_fraction,
                        }})
    current = _system_snapshot()
    receipt["system_baseline"] = current
    if current["available_memory_bytes"] is None:
        receipt.update({
            "exit_status": "CANNOT_CONFIRM",
            "stop_reason": f"AVAILABLE_MEMORY_UNMEASURABLE:{current['available_memory_error']}",
            "finished_at_utc": _utc_now(),
        })
        return receipt

    if not cpu_only:
        try:
            model_baseline = _select_workers(
                requested_workers=8,
                threads_per_worker=1,
                total_thread_budget=args.total_thread_budget,
                canary_peak_rss_bytes=args.fit_canary_peak_rss_bytes,
                available_memory_bytes=current["available_memory_bytes"],
                safety_fraction=args.memory_safety_fraction,
            )
        except ValueError as exc:
            receipt.update({
                "exit_status": "CANNOT_CONFIRM",
                "stop_reason": f"REAL_FIT_MEMORY_GUARD_REJECTED:{exc}",
                "finished_at_utc": _utc_now(),
            })
            return receipt
        receipt["model_fit_selection_using_real_canary_rss_baseline"] = model_baseline
        if model_baseline["actual_workers"] < 1:
            receipt.update({
                "exit_status": "CANNOT_CONFIRM",
                "stop_reason": "REAL_FIT_MEMORY_GUARD_SELECTED_ZERO_WORKERS",
                "finished_at_utc": _utc_now(),
            })
            return receipt

    numeric_peak_rss_bytes: int | None = config["numeric_canary_peak_rss_bytes"] if cpu_only else None
    combinations = [tuple(pair) for pair in config["calibration_combinations"]] + args.combinations
    for index, (requested_workers, threads_per_worker) in enumerate(combinations):
        before = _system_snapshot()
        if before["available_memory_bytes"] is None:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = f"AVAILABLE_MEMORY_UNMEASURABLE_BEFORE_STAGE:{before['available_memory_error']}"
            break
        try:
            numeric_selection = _select_workers(
                requested_workers=requested_workers,
                threads_per_worker=threads_per_worker,
                total_thread_budget=args.total_thread_budget,
                canary_peak_rss_bytes=(
                    args.fit_canary_peak_rss_bytes
                    if numeric_peak_rss_bytes is None
                    else numeric_peak_rss_bytes
                ),
                available_memory_bytes=before["available_memory_bytes"],
                safety_fraction=args.memory_safety_fraction,
            )
        except ValueError as exc:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = f"NUMERIC_RESOURCE_GUARD_REJECTED:{exc}"
            break

        if cpu_only:
            model_selection, model_selection_error = None, None
        else:
            try:
                model_selection = _select_workers(
                    requested_workers=requested_workers,
                    threads_per_worker=threads_per_worker,
                    total_thread_budget=args.total_thread_budget,
                    canary_peak_rss_bytes=args.fit_canary_peak_rss_bytes,
                    available_memory_bytes=before["available_memory_bytes"],
                    safety_fraction=args.memory_safety_fraction,
                )
                model_selection_error = None
            except ValueError as exc:
                model_selection = None
                model_selection_error = str(exc)

        if numeric_selection["actual_workers"] < 1:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = "NUMERIC_RESOURCE_GUARD_SELECTED_ZERO_WORKERS"
            break

        with _SystemMonitor(args.sample_interval_seconds) as monitor:
            results = _run_cpu_pool(
                workers=numeric_selection["actual_workers"],
                threads_per_worker=threads_per_worker,
                total_thread_budget=args.total_thread_budget,
                size=args.matrix_size,
                repeats=args.repeats,
                seed=args.seed + index * 1000,
                native_control_path=config.get("native_control_path", "CANARY_ACCELERATE_API"),
            )
        samples = [before, *monitor.samples]
        stage = _stage_summary(
            stage_id=(
                f"trainer_control_{requested_workers}x{threads_per_worker}"
                if config.get("native_control_path") == "TRAINER_CONTROL_PATH" else
                f"native_calibration_{requested_workers}x{threads_per_worker}"
                if requested_workers == 1
                else f"cpu_{requested_workers}x{threads_per_worker}"
            ),
            requested_workers=requested_workers,
            threads_per_worker=threads_per_worker,
            total_thread_budget=args.total_thread_budget,
            numeric_selection=numeric_selection,
            model_selection=model_selection,
            model_selection_error=model_selection_error,
            results=results,
            samples=samples,
        )
        if cpu_only:
            stage.pop("model_fit_selection_using_real_canary_rss")
            stage.pop("model_fit_selection_error")
        receipt["stages"].append(stage)
        measured_worker_peak = int(stage["max_single_process_peak_rss_bytes"])
        numeric_peak_rss_bytes = (
            measured_worker_peak
            if numeric_peak_rss_bytes is None
            else max(numeric_peak_rss_bytes, measured_worker_peak)
        )
        receipt["max_numeric_worker_peak_rss_bytes_observed"] = (
            max(int(item["max_single_process_peak_rss_bytes"]) for item in receipt["stages"])
            if cpu_only else numeric_peak_rss_bytes
        )
        if cpu_only:
            receipt["numeric_guard_peak_rss_bytes"] = numeric_peak_rss_bytes
        if not stage["pass"]:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = stage["stop_reason"]
            break
        minimum_available = stage["system_min_available_memory_bytes"]
        if minimum_available is None:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = "AVAILABLE_MEMORY_UNMEASURABLE_DURING_STAGE"
            break
        try:
            numeric_after = _select_workers(
                requested_workers=requested_workers,
                threads_per_worker=threads_per_worker,
                total_thread_budget=args.total_thread_budget,
                canary_peak_rss_bytes=numeric_peak_rss_bytes,
                available_memory_bytes=minimum_available,
                safety_fraction=args.memory_safety_fraction,
            )
        except ValueError as exc:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = f"NUMERIC_HEADROOM_LOST_AFTER_STAGE:{exc}"
            break
        stage["numeric_canary_selection_after_stage_minimum_available_memory"] = numeric_after
        if numeric_after["actual_workers"] < stage["actual_workers"]:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = "NUMERIC_CANARY_WORKER_CAP_REDUCED_BY_MEMORY_PRESSURE"
            break
        if cpu_only:
            continue
        try:
            model_after = _select_workers(
                requested_workers=model_baseline["actual_workers"],
                threads_per_worker=1,
                total_thread_budget=args.total_thread_budget,
                canary_peak_rss_bytes=args.fit_canary_peak_rss_bytes,
                available_memory_bytes=minimum_available,
                safety_fraction=args.memory_safety_fraction,
            )
        except ValueError as exc:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = f"REAL_FIT_HEADROOM_LOST_AFTER_STAGE:{exc}"
            break
        stage["model_fit_selection_after_stage_minimum_available_memory"] = model_after
        if model_after["actual_workers"] < model_baseline["actual_workers"]:
            receipt["exit_status"] = "CANNOT_CONFIRM"
            receipt["stop_reason"] = "REAL_FIT_WORKER_CAP_REDUCED_BY_CANARY_MEMORY_PRESSURE"
            break

    if receipt["exit_status"] == "RUNNING":
        receipt["exit_status"] = "SUCCESS" if receipt["stages"] else "CANNOT_CONFIRM"
        receipt["stop_reason"] = None if receipt["exit_status"] == "SUCCESS" else "NO_CPU_STAGES_COMPLETED"
    if cpu_only and receipt["exit_status"] == "SUCCESS":
        receipt["engineering_status"] = "CPU_PARALLEL_PASS_MODEL_NOT_RUN"
    receipt["finished_at_utc"] = _utc_now()
    receipt["stage_pass_count"] = sum(bool(stage["pass"]) for stage in receipt["stages"])
    receipt["max_numeric_workers_observed"] = max(
        (int(stage["actual_workers"]) for stage in receipt["stages"]), default=0
    )
    receipt["max_numeric_native_threads_observed"] = max(
        (int(stage["effective_native_threads_observed_upper_bound"]) for stage in receipt["stages"]), default=0
    )
    return receipt


def _parse_combinations(value: str, *, max_workers: int = 8) -> list[tuple[int, int]]:
    combinations: list[tuple[int, int]] = []
    for piece in value.split(","):
        match = re.fullmatch(r"\s*(\d+)x(\d+)\s*", piece)
        if match is None:
            raise argparse.ArgumentTypeError("worker combinations must use N x M form, e.g. 2x6,4x3,8x1")
        workers, threads = int(match.group(1)), int(match.group(2))
        if not (2 <= workers <= max_workers and 1 <= threads <= 6):
            raise argparse.ArgumentTypeError(f"worker combinations must be within 2..{max_workers} workers and 1..6 threads")
        combinations.append((workers, threads))
    if len(set(combinations)) != len(combinations):
        raise argparse.ArgumentTypeError("worker combinations must be unique")
    return combinations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--config-sha256", required=True)
    cli_args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", cli_args.config_sha256):
        parser.error("config SHA-256 must contain 64 lowercase hex characters")
    try:
        config, config_sha256, input_sha256 = _load_frozen_config(
            cli_args.config, cli_args.config_sha256
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    workload = config["workload"]
    args = argparse.Namespace(
        config=config,
        config_path=cli_args.config.resolve(),
        config_sha256=config_sha256,
        input_sha256=input_sha256,
        execution_id=config["execution_id"],
        output=Path(config["output_path"]),
        fit_canary_peak_rss_bytes=config.get("fit_canary_peak_rss_bytes"),
        combinations=[tuple(item) for item in config["requested_combinations"]],
        total_thread_budget=config["total_thread_budget"],
        memory_safety_fraction=config["memory_safety_fraction"],
        matrix_size=workload["matrix_size"],
        repeats=workload["repeats"],
        seed=workload["seed"],
        sample_interval_seconds=config["system_sample_interval_seconds"],
    )

    try:
        receipt = run_canary(args)
    except Exception as exc:
        receipt = {
            "schema_version": "a_share_v194.mac_parallel_canary.v1",
            "execution_id": args.execution_id,
            "started_at_utc": _utc_now(),
            "finished_at_utc": _utc_now(),
            "exit_status": "CANNOT_CONFIRM",
            "stop_reason": "CANARY_EXECUTION_EXCEPTION",
            "failure_type": type(exc).__name__,
            "safety_flags": SAFETY_FLAGS,
            "code_sha256": {
                "mac_parallel_canary194.py": adapter.sha256_file(__file__),
                "long_training_adapter.py": adapter.sha256_file(MODULE_DIR / "long_training_adapter.py"),
                "test_mac_memory_probe.py": adapter.sha256_file(MODULE_DIR / "test_mac_memory_probe.py"),
                "README_LONG_HISTORY.md": adapter.sha256_file(MODULE_DIR / "README_LONG_HISTORY.md"),
            },
            "config_path": str(args.config_path),
            "config_sha256": args.config_sha256,
            "input_path": args.config["input_path"],
            "input_sha256": args.input_sha256,
        }
    if args.config["schema_version"] == "a_share_v194.mac_parallel_canary_config.v4":
        receipt.update({"protocol": "CPU_ONLY", "model_objects_created": 0,
                        "model_fits": 0, "model_evaluation": "NOT_RUN"})
    adapter.atomic_write_json(args.output, receipt, exclusive=True)
    summary = {
        "output": str(args.output.resolve()), "execution_id": args.execution_id,
        "exit_status": receipt["exit_status"], "stop_reason": receipt.get("stop_reason"),
        "stage_pass_count": receipt.get("stage_pass_count", 0),
        "max_numeric_workers_observed": receipt.get("max_numeric_workers_observed", 0),
        "max_numeric_native_threads_observed": receipt.get("max_numeric_native_threads_observed", 0),
    }
    if args.config["schema_version"] == "a_share_v194.mac_parallel_canary_config.v4":
        summary.update({"engineering_status": receipt.get("engineering_status"),
                        "model_objects_created": 0, "model_fits": 0, "model_evaluation": "NOT_RUN"})
    else:
        summary["model_fit_selection"] = receipt.get("model_fit_selection_using_real_canary_rss_baseline")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["exit_status"] == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
