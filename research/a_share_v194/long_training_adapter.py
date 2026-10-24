"""A-share V194 process budget and local runner receipts.

This module is standard-library-only so callers can apply native thread limits
before importing NumPy, scikit-learn, or the legacy V194 model module.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import threading
import time
from typing import Any, Mapping


SAFETY_FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
FROZEN_UNIVERSE_SCOPE = "EXISTING_5533_RESEARCH_CODES_NOT_CERTIFIED_HISTORICAL_ALL_A"
NATIVE_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Hash a JSON value with the same deterministic encoding used by contracts."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(value, dict), "JSON_OBJECT_REQUIRED")
    return value


def atomic_write_json(path: str | Path, value: Mapping[str, Any], *, exclusive: bool = False) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def configure_native_thread_budget(
    *, processes: int, threads_per_process: int, total_thread_budget: int = 12,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Set actual math-library limits and reject an over-budget configuration."""
    require(type(processes) is int and processes >= 1, "PROCESS_COUNT_INVALID")
    require(type(threads_per_process) is int and threads_per_process >= 1, "THREAD_COUNT_INVALID")
    require(type(total_thread_budget) is int and 1 <= total_thread_budget <= 16, "THREAD_BUDGET_INVALID")
    require(processes * threads_per_process <= total_thread_budget, "THREAD_BUDGET_EXCEEDED")
    target = os.environ if environ is None else environ
    for name in NATIVE_THREAD_VARIABLES:
        target[name] = str(threads_per_process)
    target["OMP_DYNAMIC"] = "FALSE"
    observed = {name: target.get(name) for name in (*NATIVE_THREAD_VARIABLES, "OMP_DYNAMIC")}
    require(all(observed[name] == str(threads_per_process) for name in NATIVE_THREAD_VARIABLES), "NATIVE_THREAD_ENV_DRIFT")
    require(observed["OMP_DYNAMIC"] == "FALSE", "OMP_DYNAMIC_NOT_DISABLED")
    return {
        "processes": processes,
        "threads_per_process": threads_per_process,
        "total_thread_budget": total_thread_budget,
        "effective_native_threads": processes * threads_per_process,
        "environment": observed,
    }


def _mac_available_memory_probe() -> tuple[int | None, str, int | None]:
    """Read a conservative reclaimable-memory estimate from macOS vm_stat.

    This macOS runtime does not expose SC_AVPHYS_PAGES through os.sysconf.
    Free pages are immediately available; inactive pages can be reclaimed by
    the VM system. Speculative and purgeable counts are excluded to keep the
    estimate conservative.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/vm_stat"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"VM_STAT_{type(exc).__name__}", None

    page_size_match = re.search(
        r"^Mach Virtual Memory Statistics: \(page size of ([0-9,]+) bytes\)$",
        result.stdout,
        flags=re.MULTILINE,
    )
    if page_size_match is None:
        return None, "VM_STAT_PAGE_SIZE_UNPARSEABLE", None

    page_size = int(page_size_match.group(1).replace(",", ""))
    if page_size <= 0:
        return None, "VM_STAT_PAGE_SIZE_INVALID", None

    counts: dict[str, int] = {}
    for name in ("free", "inactive"):
        match = re.search(
            rf"^Pages {name}:\s*([0-9,]+)\.?\s*$",
            result.stdout,
            flags=re.MULTILINE,
        )
        if match is None:
            return None, f"VM_STAT_PAGES_{name.upper()}_UNPARSEABLE", page_size
        counts[name] = int(match.group(1).replace(",", ""))

    available = (counts["free"] + counts["inactive"]) * page_size
    if available <= 0:
        return None, "VM_STAT_AVAILABLE_MEMORY_NONPOSITIVE", page_size
    return available, "MAC_VM_STAT_FREE_PLUS_INACTIVE", page_size


def runtime_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = int(usage.ru_maxrss)
    # macOS reports bytes; Linux and the CI runtime report KiB.
    peak_rss_bytes = peak if sys.platform == "darwin" else peak * 1024
    memory_bytes = None
    available_memory_bytes = None
    available_memory_page_size_bytes = None
    available_memory_source = "UNAVAILABLE"
    available_memory_error = None
    try:
        available_memory_page_size_bytes = int(os.sysconf("SC_PAGE_SIZE"))
        memory_bytes = int(os.sysconf("SC_PHYS_PAGES") * available_memory_page_size_bytes)
    except (AttributeError, OSError, ValueError):
        pass
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        available_memory_bytes = int(os.sysconf("SC_AVPHYS_PAGES") * page_size)
        if available_memory_bytes <= 0:
            available_memory_bytes = None
            available_memory_error = "SC_AVPHYS_PAGES_NONPOSITIVE"
        else:
            available_memory_source = "SC_AVPHYS_PAGES"
            available_memory_page_size_bytes = page_size
    except (AttributeError, OSError, ValueError):
        available_memory_bytes = None
        available_memory_error = "SC_AVPHYS_PAGES_UNAVAILABLE"
    if available_memory_bytes is None and sys.platform == "darwin":
        available_memory_bytes, fallback_status, fallback_page_size = _mac_available_memory_probe()
        if available_memory_bytes is None:
            available_memory_error = fallback_status
        else:
            available_memory_source = fallback_status
            available_memory_error = None
            available_memory_page_size_bytes = fallback_page_size
    if (
        available_memory_bytes is not None
        and memory_bytes is not None
        and available_memory_bytes > memory_bytes
    ):
        available_memory_bytes = None
        available_memory_source = "UNAVAILABLE"
        available_memory_error = "AVAILABLE_MEMORY_EXCEEDS_PHYSICAL_MEMORY"
        available_memory_page_size_bytes = None
    return {
        "pid": os.getpid(),
        "host": platform.node(),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": memory_bytes,
        "available_memory_bytes": available_memory_bytes,
        "available_memory_page_size_bytes": available_memory_page_size_bytes,
        "available_memory_source": available_memory_source,
        "available_memory_error": available_memory_error,
        "process_peak_rss_bytes": peak_rss_bytes,
        "user_cpu_seconds": float(usage.ru_utime),
        "system_cpu_seconds": float(usage.ru_stime),
        "sampled_at_utc": utc_now(),
    }


def select_safe_fit_workers(
    *, requested_workers: int, threads_per_worker: int, total_thread_budget: int,
    canary_peak_rss_bytes: int, available_memory_bytes: int | None,
    memory_safety_fraction: float = 0.5,
) -> dict[str, Any]:
    """Cap OOF process workers using the measured fit canary and current headroom."""
    require(type(requested_workers) is int and requested_workers >= 1, "FIT_WORKER_COUNT_INVALID")
    require(type(threads_per_worker) is int and threads_per_worker >= 1, "THREAD_COUNT_INVALID")
    require(type(total_thread_budget) is int and 1 <= total_thread_budget <= 16, "THREAD_BUDGET_INVALID")
    require(type(canary_peak_rss_bytes) is int and canary_peak_rss_bytes > 0, "FIT_CANARY_RSS_REQUIRED")
    require(type(memory_safety_fraction) in (int, float), "MEMORY_SAFETY_FRACTION_INVALID")
    require(0.2 <= memory_safety_fraction <= 1.0, "MEMORY_SAFETY_FRACTION_INVALID")
    thread_cap = total_thread_budget // threads_per_worker
    require(thread_cap >= 1, "THREAD_BUDGET_EXCEEDED")
    if available_memory_bytes is None:
        return {
            "requested_workers": requested_workers,
            "actual_workers": 1,
            "threads_per_worker": threads_per_worker,
            "effective_threads": threads_per_worker,
            "canary_peak_rss_bytes": canary_peak_rss_bytes,
            "available_memory_bytes": None,
            "memory_safety_fraction": memory_safety_fraction,
            "selection_reason": "AVAILABLE_MEMORY_UNMEASURABLE_SERIAL_FALLBACK",
        }
    require(type(available_memory_bytes) is int and available_memory_bytes > 0, "AVAILABLE_MEMORY_INVALID")
    if canary_peak_rss_bytes > available_memory_bytes:
        raise ValueError("FIT_CANARY_PEAK_EXCEEDS_AVAILABLE_MEMORY")
    memory_cap = int((available_memory_bytes * memory_safety_fraction) // canary_peak_rss_bytes)
    require(memory_cap >= 1, "FIT_CANARY_EXCEEDS_MEMORY_SAFETY_HEADROOM")
    actual = min(requested_workers, thread_cap, memory_cap)
    return {
        "requested_workers": requested_workers,
        "actual_workers": actual,
        "threads_per_worker": threads_per_worker,
        "effective_threads": actual * threads_per_worker,
        "thread_cap_workers": thread_cap,
        "memory_cap_workers": memory_cap,
        "canary_peak_rss_bytes": canary_peak_rss_bytes,
        "available_memory_bytes": available_memory_bytes,
        "memory_safety_fraction": memory_safety_fraction,
        "selection_reason": "MEASURED_CANARY_RSS_AND_CURRENT_AVAILABLE_MEMORY",
    }


def read_frozen_universe_codes(path: str | Path) -> list[str]:
    path = Path(path)
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if lines and lines[0] == "code":
        lines = lines[1:]
    codes = lines
    require(len(codes) == 5533, "FROZEN_UNIVERSE_CODE_COUNT_MISMATCH")
    require(len(set(codes)) == 5533, "FROZEN_UNIVERSE_DUPLICATE_CODES")
    require(codes == sorted(codes), "FROZEN_UNIVERSE_CODE_ORDER_INVALID")
    require(all(re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", code) for code in codes), "FROZEN_UNIVERSE_CODE_FORMAT_INVALID")
    return codes


HISTORY_EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_full_history_20261024")
HISTORY_TARGET_CAP = "2026-10-22"
HISTORY_EXPOSED_TARGETS = {"2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"}


def history_output_path(value: str | Path, *, roots: tuple[str, ...] = ("inputs", "build", "runs", "reports")) -> Path:
    """Resolve before writing; a symlink cannot redirect a new run into old outputs."""
    require(bool(str(value)), "HISTORY_OUTPUT_PATH_REQUIRED")
    path = Path(value).resolve()
    root = HISTORY_EVIDENCE_ROOT.resolve()
    require(any(path.is_relative_to(root / part) and path != root / part for part in roots),
            "HISTORY_OUTPUT_OUTSIDE_NEW_EVIDENCE_ROOT")
    return path


def _history_bound_json(ref: Any, code: str) -> tuple[Path, dict[str, Any]]:
    require(isinstance(ref, Mapping), code + "_BINDING_REQUIRED")
    path = Path(str(ref.get("path", ""))).resolve()
    expected = ref.get("sha256")
    require(path.is_file() and isinstance(expected, str) and len(expected) == 64, code + "_BINDING_REQUIRED")
    require(sha256_file(path) == expected, code + "_SHA_DRIFT")
    return path, load_json(path)


def verify_history_input_binding(config: Mapping[str, Any], *, purpose: str = "fit") -> dict[str, Any]:
    """Accept a new, exact independent input review, never the old input PASS.

    A source-only review permits input construction to produce its first real
    parity evidence. Fitting still requires the final independent input PASS.
    """
    binding = config.get("history_binding")
    require(isinstance(binding, Mapping), "HISTORY_INPUT_BINDING_REQUIRED")
    require(binding.get("schema") == "V194_FULL_HISTORY_INPUT_BINDING_V1", "HISTORY_BINDING_SCHEMA_DRIFT")
    require(binding.get("target_date_cap") == HISTORY_TARGET_CAP, "HISTORY_TARGET_CAP_DRIFT")
    require(set(binding.get("exposed_targets_excluded", [])) == HISTORY_EXPOSED_TARGETS,
            "HISTORY_EXPOSED_TARGETS_DRIFT")
    history_output_path(config.get("output_dir", config.get("build_dir", "")))
    qfq_ref = binding.get("qfq_manifest")
    _, qfq = _history_bound_json(qfq_ref, "QFQ_INPUT")
    review_path, receipt = _history_bound_json(binding.get("input_review"), "CURRENT_HISTORY_INPUT_REVIEW")
    require(review_path.is_relative_to(HISTORY_EVIDENCE_ROOT.resolve()), "CURRENT_HISTORY_REVIEW_OUTSIDE_NEW_EVIDENCE")
    require(purpose in {"fit", "input_build"}, "HISTORY_BINDING_PURPOSE_INVALID")
    source_only = purpose == "input_build" and receipt.get("status") == "SOURCE_BOUND_REVIEW_ONLY"
    if source_only:
        require(receipt.get("review_scope") == "RAW_EVENT_SCHEMA_CODE_BINDING_ONLY"
                and receipt.get("formula_or_label_values_verified") is False
                and receipt.get("fit_allowed") is False, "SOURCE_ONLY_REVIEW_SCOPE_DRIFT")
    else:
        require(receipt.get("status") == "PASS_RECONSTRUCTED_FULL_HISTORY_INPUT", "CURRENT_HISTORY_INPUT_REVIEW_NOT_PASS")
    require(receipt.get("maximum_claim") == "DIRECTION_ONLY", "HISTORY_REVIEW_CLAIM_DRIFT")
    require(receipt.get("qfq_manifest") == qfq_ref, "HISTORY_REVIEW_QFQ_BINDING_DRIFT")
    require(receipt.get("v194_input_abi_verified") is True, "V194_QFQ_INPUT_ABI_UNVERIFIED")
    require(isinstance(qfq.get("consumer_abi"), str) and qfq["consumer_abi"] != "UNBOUND",
            "V194_QFQ_INPUT_ABI_UNBOUND")
    require(receipt.get("consumer_abi") == qfq["consumer_abi"], "V194_QFQ_INPUT_ABI_DRIFT")
    if not source_only:
        require(receipt.get("raw_event_target_d_label_parity") is True, "TARGET_D_RAW_EVENT_LABEL_PARITY_UNVERIFIED")
    return {"review": receipt, "qfq_manifest": qfq, "review_path": str(review_path),
            "review_sha256": binding["input_review"]["sha256"]}


class RunnerHeartbeat(AbstractContextManager["RunnerHeartbeat"]):
    """Write durable PID, heartbeat, checkpoint, and terminal receipts locally."""

    def __init__(
        self, run_dir: str | Path, *, route_id: str, execution_id: str,
        heartbeat_seconds: float = 30.0, runtime_budget: Mapping[str, Any] | None = None,
        run_stage: str = "unknown",
    ) -> None:
        require(heartbeat_seconds >= 5.0, "HEARTBEAT_INTERVAL_TOO_SHORT")
        self.run_dir = Path(run_dir)
        self.route_id = route_id
        self.execution_id = execution_id
        self.heartbeat_seconds = heartbeat_seconds
        self.runtime_budget = dict(runtime_budget or {})
        self.run_stage = run_stage
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started_at = utc_now()
        self.runtime_path = self.run_dir / "runtime_events.jsonl"

    def _append(self, row: Mapping[str, Any]) -> None:
        payload = {"schema_version": "a_share_v194.runtime_event.v1", **row, **SAFETY_FLAGS}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._lock:
            with self.runtime_path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def __enter__(self) -> "RunnerHeartbeat":
        self.run_dir.mkdir(parents=True, exist_ok=True)
        require(not (self.run_dir / "RUNNER_STARTED.json").exists(), "RUNNER_RECEIPT_ALREADY_EXISTS")
        require(not self.runtime_path.exists(), "RUNTIME_EVENTS_ALREADY_EXISTS")
        started = {
            "schema_version": "a_share_v194.runner_started.v1",
            "route_id": self.route_id,
            "execution_id": self.execution_id,
            "run_stage": self.run_stage,
            "pid": os.getpid(),
            "started_at_utc": self._started_at,
            "heartbeat_seconds": self.heartbeat_seconds,
            "runtime_budget": self.runtime_budget,
            "runtime": runtime_snapshot(),
            **SAFETY_FLAGS,
        }
        atomic_write_json(self.run_dir / "RUNNER_STARTED.json", started, exclusive=True)
        self._append({**started, "event": "RUNNER_STARTED", "terminal": False})
        self._thread = threading.Thread(target=self._heartbeat_loop, name="v194-heartbeat", daemon=True)
        self._thread.start()
        return self

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            self._append({
                "route_id": self.route_id,
                "execution_id": self.execution_id,
                "pid": os.getpid(),
                "event": "HEARTBEAT",
                "heartbeat_at_utc": utc_now(),
                "runtime": runtime_snapshot(),
                "terminal": False,
            })

    def checkpoint(self, name: str, artifact_path: str | Path, metrics: Mapping[str, Any] | None = None) -> None:
        path = Path(artifact_path)
        require(path.exists(), "CHECKPOINT_ARTIFACT_MISSING")
        self._append({
            "route_id": self.route_id,
            "execution_id": self.execution_id,
            "pid": os.getpid(),
            "event": "CHECKPOINT",
            "checkpoint": name,
            "artifact_path": str(path),
            "artifact_sha256": sha256_file(path) if path.is_file() else None,
            "metrics": dict(metrics or {}),
            "recorded_at_utc": utc_now(),
            "runtime": runtime_snapshot(),
            "terminal": False,
        })

    def set_runtime_budget(self, runtime_budget: Mapping[str, Any]) -> None:
        """Persist the final measured worker choice after OOF input loading."""
        self.runtime_budget = dict(runtime_budget)
        self._append({
            "route_id": self.route_id,
            "execution_id": self.execution_id,
            "run_stage": self.run_stage,
            "pid": os.getpid(),
            "event": "RUNTIME_BUDGET_SELECTED",
            "runtime_budget": self.runtime_budget,
            "recorded_at_utc": utc_now(),
            "runtime": runtime_snapshot(),
            "terminal": False,
        })

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, min(self.heartbeat_seconds, 5.0)))
        terminal = {
            "schema_version": "a_share_v194.runner_terminal.v1",
            "route_id": self.route_id,
            "execution_id": self.execution_id,
            "pid": os.getpid(),
            "exit_status": "SUCCESS" if exc is None else "FAILED",
            "error_type": None if exc is None else type(exc).__name__,
            "error": None if exc is None else str(exc)[:500],
            "started_at_utc": self._started_at,
            "finished_at_utc": utc_now(),
            "run_stage": self.run_stage,
            "runtime_budget": self.runtime_budget,
            "runtime": runtime_snapshot(),
            "terminal": True,
            **SAFETY_FLAGS,
        }
        atomic_write_json(self.run_dir / "RUNNER_TERMINAL.json", terminal, exclusive=True)
        self._append({**terminal, "event": "RUNNER_TERMINAL"})
        return False


def verify_independent_input_pass(config: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless the exact manifest has an independently reviewed input PASS.

    The R2 coverage-delta receipt is deliberately a bounded research-input PASS,
    not a whole-input/passport certification. Its exact R2 -> R1 -> parent/child
    chain is checked here so runtime callers cannot promote the broader status.
    """
    if config.get("history_binding") is not None:
        current = verify_history_input_binding(config)
        manifest_path = Path(str(config.get("input_manifest_path", ""))).resolve()
        require(manifest_path.is_relative_to(HISTORY_EVIDENCE_ROOT.resolve() / "inputs"), "HISTORY_MANIFEST_OUTSIDE_NEW_INPUTS")
        require(Path(str(config.get("input_manifest", ""))).resolve() == manifest_path, "PIPELINE_INPUT_MANIFEST_PATH_DRIFT")
        expected = config.get("input_manifest_sha256")
        require(manifest_path.is_file() and sha256_file(manifest_path) == expected, "INPUT_MANIFEST_SHA_DRIFT")
        manifest = load_json(manifest_path)
        receipt = current["review"]
        require(receipt.get("input_manifest_path") == str(manifest_path) and receipt.get("input_manifest_sha256") == expected,
                "CURRENT_HISTORY_REVIEW_MANIFEST_DRIFT")
        universe = config.get("frozen_universe", {})
        code_path = Path(str(universe.get("code_list_path", ""))).resolve()
        require(code_path.is_file() and sha256_file(code_path) == universe.get("code_list_sha256"), "FROZEN_UNIVERSE_SHA_DRIFT")
        codes = read_frozen_universe_codes(code_path)
        require(universe.get("code_count") == len(codes), "FROZEN_UNIVERSE_COUNT_MUST_BE_5533")
        for record in (manifest.get("research_code_list", {}), receipt.get("research_code_list", {})):
            require(record.get("path") == str(code_path) and record.get("sha256") == universe.get("code_list_sha256")
                    and record.get("count") == len(codes), "CURRENT_HISTORY_UNIVERSE_BINDING_DRIFT")
        require(receipt.get("candidate_truth_same_universe") is True, "REVIEW_CANDIDATE_TRUTH_UNIVERSE_MISMATCH")
        require(manifest.get("qfq_manifest") == config["history_binding"]["qfq_manifest"], "HISTORY_MANIFEST_QFQ_DRIFT")
        return {"status": receipt["status"], "review_scope": "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT",
                "bounded_research_input_readiness": "PASS", "whole_input_status": "CANNOT_CONFIRM", "maximum_claim": "DIRECTION_ONLY",
                "input_manifest_path": str(manifest_path), "input_manifest_sha256": expected,
                "review_receipt_path": current["review_path"], "review_receipt_sha256": current["review_sha256"],
                "universe_scope": manifest.get("universe_scope"), "universe_code_list_path": str(code_path),
                "universe_code_list_sha256": universe["code_list_sha256"], "universe_code_count": len(codes),
                "candidate_truth_same_universe": True}
    manifest_path = Path(str(config.get("input_manifest_path", "")))
    pipeline_manifest_path = Path(str(config.get("input_manifest", "")))
    manifest_sha = config.get("input_manifest_sha256")
    review = config.get("independent_input_review")
    require(manifest_path.is_file() and isinstance(manifest_sha, str) and bool(manifest_sha), "INPUT_MANIFEST_BINDING_REQUIRED")
    require(pipeline_manifest_path.is_file(), "PIPELINE_INPUT_MANIFEST_BINDING_REQUIRED")
    require(pipeline_manifest_path.resolve() == manifest_path.resolve(), "PIPELINE_INPUT_MANIFEST_PATH_DRIFT")
    require(sha256_file(manifest_path) == manifest_sha, "INPUT_MANIFEST_SHA_DRIFT")
    require(isinstance(review, Mapping), "INDEPENDENT_INPUT_REVIEW_REQUIRED")
    review_path = Path(str(review.get("path", "")))
    review_sha = review.get("sha256")
    require(review_path.is_file() and isinstance(review_sha, str) and bool(review_sha), "INDEPENDENT_INPUT_REVIEW_BINDING_REQUIRED")
    require(sha256_file(review_path) == review_sha, "INDEPENDENT_INPUT_REVIEW_SHA_DRIFT")
    receipt = load_json(review_path)
    status = receipt.get("status", receipt.get("decision"))
    bounded_r2 = status == "PASS_R2_COVERAGE_METADATA_DELTA"
    manifest = load_json(manifest_path)
    if bounded_r2:
        require(receipt.get("bounded_research_input_readiness") == "PASS", "BOUNDED_RESEARCH_INPUT_REVIEW_NOT_PASS")
        require(receipt.get("whole_input_status") == "CANNOT_CONFIRM", "WHOLE_INPUT_STATUS_MUST_REMAIN_CANNOT_CONFIRM")
        require(receipt.get("maximum_claim") == "DIRECTION_ONLY; NOT_HISTORICAL_ALL_A_CERTIFICATION; NO_MODEL_EVALUATION",
                "BOUNDED_REVIEW_MAXIMUM_CLAIM_DRIFT")
        require(receipt.get("bounded_research_input_scope") ==
                "Current reconstructed research-input metadata and frozen parent bindings only; not a historical point-in-time certification.",
                "BOUNDED_REVIEW_SCOPE_DRIFT")
        reviewed = receipt.get("reviewed_binding")
        require(isinstance(reviewed, Mapping), "R2_REVIEWED_BINDING_MISSING")
        child_ref = reviewed.get("child_manifest")
        parent_ref = reviewed.get("parent_manifest")
        r1_ref = reviewed.get("r1_review_result")
        parent_binding = manifest.get("parent_manifest")
        require(isinstance(child_ref, Mapping) and isinstance(parent_ref, Mapping) and isinstance(r1_ref, Mapping),
                "R2_CHAIN_BINDING_INCOMPLETE")
        require(Path(str(child_ref.get("path", ""))).resolve() == manifest_path.resolve(), "R2_CHILD_MANIFEST_PATH_DRIFT")
        require(child_ref.get("sha256") == manifest_sha and child_ref.get("same_build_execution_id") is True,
                "R2_CHILD_MANIFEST_SHA_OR_EXECUTION_DRIFT")
        require(isinstance(parent_binding, Mapping), "INPUT_PARENT_MANIFEST_BINDING_REQUIRED")
        parent_path = Path(str(parent_binding.get("path", ""))).resolve()
        parent_sha = parent_binding.get("sha256")
        require(Path(str(parent_ref.get("path", ""))).resolve() == parent_path and parent_ref.get("sha256") == parent_sha,
                "R2_PARENT_MANIFEST_BINDING_DRIFT")
        require(parent_path.is_file() and isinstance(parent_sha, str) and sha256_file(parent_path) == parent_sha,
                "INPUT_PARENT_MANIFEST_SHA_DRIFT")
        require(reviewed.get("registered_event_hashes_recomputed_from_registry") is True,
                "R2_REGISTERED_EVENT_BINDING_NOT_VERIFIED")
        # The R2 result binds the metadata child to its exact coverage file and
        # dictionary.  A matching manifest SHA alone is not enough if a caller
        # accidentally supplies the full parent or swaps one of these files.
        child_file_bindings = manifest.get("files")
        require(isinstance(child_file_bindings, Mapping), "R2_CHILD_FILE_BINDINGS_MISSING")
        for manifest_key, review_key in (("coverage", "coverage"), ("dictionary", "data_dictionary")):
            reviewed_file = reviewed.get(review_key)
            manifest_file = child_file_bindings.get(manifest_key)
            require(isinstance(reviewed_file, Mapping) and isinstance(manifest_file, Mapping),
                    "R2_METADATA_FILE_BINDING_MISSING:" + manifest_key)
            reviewed_file_path = Path(str(reviewed_file.get("path", ""))).resolve()
            manifest_file_path = Path(str(manifest_file.get("path", ""))).resolve()
            reviewed_file_sha = reviewed_file.get("sha256")
            require(reviewed_file_path == manifest_file_path and reviewed_file.get("path") == manifest_file.get("path"),
                    "R2_METADATA_FILE_PATH_DRIFT:" + manifest_key)
            require(reviewed_file_sha == manifest_file.get("sha256"),
                    "R2_METADATA_FILE_SHA_BINDING_DRIFT:" + manifest_key)
            require(reviewed_file_path.is_file() and isinstance(reviewed_file_sha, str)
                    and sha256_file(reviewed_file_path) == reviewed_file_sha,
                    "R2_METADATA_FILE_SHA_DRIFT:" + manifest_key)
            if manifest_key == "coverage":
                require(type(reviewed_file.get("rows")) is int
                        and reviewed_file.get("rows") == manifest_file.get("rows"),
                        "R2_COVERAGE_ROW_COUNT_BINDING_DRIFT")

        # Preserve the complete construction ancestry as separate identities:
        # R2 metadata child -> long parent manifest -> input-build contract ->
        # short-R1 source manifest.  This is provenance only; it does not
        # promote any historical, calendar, or passport status.
        lineage = config.get("input_source_lineage")
        require(isinstance(lineage, Mapping), "INPUT_SOURCE_LINEAGE_BINDING_REQUIRED")
        build_ref = lineage.get("input_build_contract")
        short_r1_ref = lineage.get("short_r1_source_manifest")
        require(isinstance(build_ref, Mapping) and isinstance(short_r1_ref, Mapping),
                "INPUT_SOURCE_LINEAGE_BINDING_INCOMPLETE")
        build_path = Path(str(build_ref.get("path", ""))).resolve()
        build_sha = build_ref.get("sha256")
        short_path = Path(str(short_r1_ref.get("path", ""))).resolve()
        short_sha = short_r1_ref.get("sha256")
        require(build_path.is_file() and isinstance(build_sha, str) and sha256_file(build_path) == build_sha,
                "INPUT_BUILD_CONTRACT_SHA_DRIFT")
        require(short_path.is_file() and isinstance(short_sha, str) and sha256_file(short_path) == short_sha,
                "SHORT_R1_SOURCE_MANIFEST_SHA_DRIFT")
        build_contract = load_json(build_path)
        build_sources = build_contract.get("frozen_source_bindings")
        build_outputs = build_contract.get("input_identity", {}).get("expected_output_paths")
        require(isinstance(build_sources, Mapping) and build_sources.get(str(short_path)) == short_sha,
                "SHORT_R1_SOURCE_NOT_BOUND_BY_INPUT_BUILD_CONTRACT")
        require(isinstance(build_outputs, Mapping)
                and Path(str(build_outputs.get("input_build_dir", ""))).resolve() == parent_path.parent,
                "LONG_PARENT_NOT_OUTPUT_OF_BOUND_INPUT_BUILD_CONTRACT")
        r1_path = Path(str(r1_ref.get("path", ""))).resolve()
        r1_sha = r1_ref.get("sha256")
        require(r1_path.is_file() and isinstance(r1_sha, str) and sha256_file(r1_path) == r1_sha,
                "R1_REVIEW_RESULT_SHA_DRIFT")
        r1 = load_json(r1_path)
        r1_manifest = r1.get("manifest")
        require(isinstance(r1_manifest, Mapping) and Path(str(r1_manifest.get("path", ""))).resolve() == parent_path
                and r1_manifest.get("sha256") == parent_sha, "R1_PARENT_MANIFEST_BINDING_DRIFT")
        component = r1.get("component_vs_full_status")
        verified = r1.get("verified")
        require(isinstance(component, Mapping) and component.get("source_code_and_universe_canary_component") == "PASS",
                "R1_FIXED_UNIVERSE_COMPONENT_NOT_PASS")
        require(isinstance(verified, Mapping) and verified.get("code_list_and_stock_coverage") ==
                "PASS_EXACT_FIXED_5533_RESEARCH_POOL_NOT_ALL_A", "R1_FIXED_UNIVERSE_EVIDENCE_MISSING")
        candidate_check = verified.get("candidate_tables")
        truth_check = verified.get("truth")
        require(isinstance(candidate_check, Mapping) and candidate_check.get("candidate_keys_unique_ordered_and_within_pool") is True,
                "R1_CANDIDATE_UNIVERSE_BINDING_MISSING")
        require(isinstance(truth_check, Mapping) and truth_check.get("all_codes_within_fixed_pool") is True,
                "R1_TRUTH_UNIVERSE_BINDING_MISSING")
        research_codes = manifest.get("research_code_list")
        parent = load_json(parent_path)
        parent_codes = parent.get("research_code_list")
        require(isinstance(research_codes, Mapping) and isinstance(parent_codes, Mapping), "RESEARCH_CODE_LIST_BINDING_MISSING")
        code_path = Path(str(research_codes.get("path", ""))).resolve()
        code_sha = research_codes.get("sha256")
        code_count = research_codes.get("count")
        require(type(code_count) is int and code_count == 5533, "RESEARCH_CODE_LIST_COUNT_DRIFT")
        require(research_codes == parent_codes, "CHILD_PARENT_RESEARCH_CODE_LIST_DRIFT")
        require(code_path.is_file() and isinstance(code_sha, str) and sha256_file(code_path) == code_sha,
                "RESEARCH_CODE_LIST_SHA_DRIFT")
        read_frozen_universe_codes(code_path)
        evidence_paths = r1.get("evidence_paths")
        require(isinstance(evidence_paths, list), "R1_EVIDENCE_PATHS_MISSING")
        code_evidence = [entry for entry in evidence_paths if isinstance(entry, Mapping)
                         and Path(str(entry.get("path", ""))).resolve() == code_path]
        require(len(code_evidence) == 1 and code_evidence[0].get("sha256") == code_sha,
                "R1_RESEARCH_CODE_LIST_BINDING_DRIFT")

        # R2 reviews the child and its exact parent. Require every model input
        # contract field used by the runner to be unchanged across that edge.
        for key in ("schema", "research_code_list", "universe_scope", "technical_features",
                    "source_state_columns", "label_definition", "formula_identity", "signal_date_range",
                    "target_date_range", "eligible_target_dates", "exposed_targets_excluded"):
            require(manifest.get(key) == parent.get(key), "CHILD_PARENT_MODEL_BINDING_DRIFT:" + key)
        parent_files = parent.get("files")
        child_files = manifest.get("files")
        require(isinstance(parent_files, Mapping) and isinstance(child_files, Mapping), "CHILD_PARENT_FILE_BINDINGS_MISSING")
        for key in ("candidates", "truth", "calendar", "date_policy", "raw_formula_natural"):
            require(child_files.get(key) == parent_files.get(key), "CHILD_PARENT_MODEL_FILE_DRIFT:" + key)
        require(manifest.get("universe_scope") == "Exact accepted 5,533 research code keys; not all-A historical certification.",
                "R2_FIXED_UNIVERSE_SCOPE_DRIFT")
        require(manifest.get("technical_features") == [
            "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS",
            "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO",
        ], "R2_TECHNICAL_FEATURE_BINDING_DRIFT")
        require(manifest.get("source_state_columns") == ["source_fupan", "source_stage7", "source_research"],
                "R2_SOURCE_STATE_BINDING_DRIFT")
        require(manifest.get("label_definition") ==
                "close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor.",
                "R2_LABEL_BINDING_DRIFT")
        require(manifest.get("formula_identity") == "FORMULA255_OFFLINE", "R2_FORMULA_IDENTITY_DRIFT")
        require(receipt.get("coverage_metadata_delta") == "PASS" or
                receipt.get("boundary_status", {}).get("coverage_metadata_delta") == "PASS",
                "R2_COVERAGE_METADATA_DELTA_NOT_PASS")
        bound_manifest_sha = child_ref["sha256"]
        bound_manifest_path = child_ref["path"]
        review_scope = "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT"
        bounded_readiness = "PASS"
        whole_input_status = "CANNOT_CONFIRM"
        maximum_claim = "DIRECTION_ONLY"
        reviewed_universe_path = str(code_path)
        reviewed_universe_sha = code_sha
        reviewed_universe_count = code_count
        candidate_truth_same_universe = True
    else:
        require(status in {"PASS", "PASS_INPUT_PASSPORT", "PASS_LONG_INPUT_PASSPORT"}, "INDEPENDENT_INPUT_REVIEW_NOT_PASS")
        bound_manifest_sha = receipt.get("input_manifest_sha256", receipt.get("manifest_sha256"))
        bound_manifest_path = receipt.get("input_manifest_path", receipt.get("manifest_path"))
        review_scope = "INDEPENDENT_INPUT_PASSPORT"
        bounded_readiness = None
        whole_input_status = status
        maximum_claim = None
        reviewed_universe_path = receipt.get("universe_code_list_path")
        reviewed_universe_sha = receipt.get("universe_code_list_sha256")
        reviewed_universe_count = receipt.get("universe_code_count")
        candidate_truth_same_universe = receipt.get("candidate_truth_same_universe")
    require(bound_manifest_sha == manifest_sha, "REVIEW_MANIFEST_BINDING_DRIFT")
    if bound_manifest_path is not None:
        require(Path(bound_manifest_path).resolve() == manifest_path.resolve(), "REVIEW_MANIFEST_PATH_DRIFT")
    universe = config.get("frozen_universe")
    require(isinstance(universe, Mapping), "FROZEN_UNIVERSE_BINDING_REQUIRED")
    universe_path = Path(str(universe.get("code_list_path", "")))
    universe_sha = universe.get("code_list_sha256")
    universe_count = universe.get("code_count")
    require(universe_path.is_file() and isinstance(universe_sha, str) and bool(universe_sha), "FROZEN_UNIVERSE_FILE_BINDING_REQUIRED")
    require(type(universe_count) is int and universe_count == 5533, "FROZEN_UNIVERSE_COUNT_MUST_BE_5533")
    require(sha256_file(universe_path) == universe_sha, "FROZEN_UNIVERSE_SHA_DRIFT")
    read_frozen_universe_codes(universe_path)
    if bounded_r2:
        manifest_codes = manifest["research_code_list"]
        require(universe.get("scope") == manifest.get("universe_scope"), "CONFIG_UNIVERSE_SCOPE_DRIFT")
        require(universe_count == manifest_codes.get("count"), "MANIFEST_UNIVERSE_COUNT_DRIFT")
        require(universe_sha == manifest_codes.get("sha256"), "MANIFEST_UNIVERSE_SHA_DRIFT")
        require(Path(str(manifest_codes.get("path", ""))).resolve() == universe_path.resolve(), "MANIFEST_UNIVERSE_PATH_DRIFT")
        require(reviewed_universe_count == universe_count, "REVIEW_UNIVERSE_COUNT_DRIFT")
        require(reviewed_universe_sha == universe_sha, "REVIEW_UNIVERSE_SHA_DRIFT")
        require(Path(str(reviewed_universe_path)).resolve() == universe_path.resolve(), "REVIEW_UNIVERSE_PATH_DRIFT")
        require(candidate_truth_same_universe is True, "REVIEW_CANDIDATE_TRUTH_UNIVERSE_MISMATCH")
        universe_scope = str(manifest.get("universe_scope"))
    else:
        require(manifest.get("universe_scope") == FROZEN_UNIVERSE_SCOPE, "FROZEN_UNIVERSE_SCOPE_DRIFT")
        require(manifest.get("universe_code_count") == universe_count, "MANIFEST_UNIVERSE_COUNT_DRIFT")
        require(manifest.get("universe_code_list_sha256") == universe_sha, "MANIFEST_UNIVERSE_SHA_DRIFT")
        require(Path(str(manifest.get("universe_code_list_path", ""))).resolve() == universe_path.resolve(), "MANIFEST_UNIVERSE_PATH_DRIFT")
        require(manifest.get("candidate_truth_same_universe") is True, "CANDIDATE_TRUTH_UNIVERSE_MISMATCH")
        require(reviewed_universe_count == universe_count, "REVIEW_UNIVERSE_COUNT_DRIFT")
        require(reviewed_universe_sha == universe_sha, "REVIEW_UNIVERSE_SHA_DRIFT")
        require(candidate_truth_same_universe is True, "REVIEW_CANDIDATE_TRUTH_UNIVERSE_MISMATCH")
        require(Path(str(reviewed_universe_path)).resolve() == universe_path.resolve(), "REVIEW_UNIVERSE_PATH_DRIFT")
        universe_scope = FROZEN_UNIVERSE_SCOPE
    return {
        "status": status,
        "review_scope": review_scope,
        "bounded_research_input_readiness": bounded_readiness,
        "whole_input_status": whole_input_status,
        "maximum_claim": maximum_claim,
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": manifest_sha,
        "review_receipt_path": str(review_path),
        "review_receipt_sha256": review_sha,
        "universe_scope": universe_scope,
        "universe_code_list_path": str(universe_path),
        "universe_code_list_sha256": universe_sha,
        "universe_code_count": universe_count,
        "candidate_truth_same_universe": True,
    }
