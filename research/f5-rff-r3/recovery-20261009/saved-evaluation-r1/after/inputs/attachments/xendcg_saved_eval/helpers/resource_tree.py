"""Spawn-based whole-tree wall/RSS supervision using the accepted F5 helpers."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping


class ResourceLimitError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json_exclusive(path: Path, payload: Mapping[str, Any]) -> str:
    """Publish a complete JSON file atomically without overwriting prior evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)  # atomic create; fails closed if evidence already exists
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return hashlib.sha256(raw).hexdigest()


def write_failure_evidence_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    """Public narrow helper used by the existing saved-evaluation owner."""
    return _atomic_json_exclusive(Path(path), payload)


def _target_from_descriptor(descriptor: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], None]:
    path = Path(str(descriptor.get("path", ""))).resolve()
    expected_sha = str(descriptor.get("sha256", ""))
    module_name = str(descriptor.get("module_name", "f5_monitored_target"))
    callable_name = str(descriptor.get("callable", "run_saved_evaluation"))
    if not path.is_file() or not expected_sha or _sha256_file(path) != expected_sha:
        raise ImportError("MONITORED_TARGET_SOURCE_SHA_MISMATCH")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MONITORED_TARGET_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    target = getattr(module, callable_name, None)
    if not callable(target):
        raise ImportError(f"MONITORED_TARGET_CALLABLE_MISSING:{callable_name}")
    return target


def _child_failure_payload(
    *, stage: str, exc: BaseException, source_files: Mapping[str, Any],
    target_descriptor: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": "F5_SAVED_EVALUATION_CHILD_ERROR_V1",
        "status": "FAILED",
        "stage": stage,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": traceback.format_exc(),
        "exit_code": None,
        "exit_code_state": "PENDING_PARENT_PROCESS_JOIN",
        "source_files": dict(source_files),
        "target_descriptor": dict(target_descriptor) if target_descriptor is not None else None,
    }


def _worker_process_entry(
    target: Callable[[Mapping[str, Any]], None] | None,
    target_descriptor: Mapping[str, Any] | None,
    payload: Mapping[str, Any],
    child_error_path: str | None,
    source_files: Mapping[str, Any],
) -> None:
    stage = "CHILD_SETUP"
    try:
        # Place the worker and any reader/fit/evaluator descendants in a private
        # session so a monitor failure can stop the complete known execution tree
        # even when psutil denies descendant enumeration.
        if hasattr(os, "setsid"):
            os.setsid()
        if target_descriptor is not None:
            stage = "TARGET_IMPORT"
            target = _target_from_descriptor(target_descriptor)
        if target is None:
            raise RuntimeError("MONITORED_TARGET_UNAVAILABLE")
        stage = "WORKER_TARGET"
        target(payload)
    except BaseException as exc:
        if child_error_path:
            path = Path(child_error_path)
            if not path.exists():
                try:
                    _atomic_json_exclusive(path, _child_failure_payload(
                        stage=stage, exc=exc, source_files=source_files,
                        target_descriptor=target_descriptor,
                    ))
                except BaseException:
                    pass
        raise


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _thread_limits_for_spawn(threads: int):
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLAS_NUM_THREADS")
    prior = {key: (key in os.environ, os.environ.get(key)) for key in keys}
    try:
        for key in keys:
            os.environ[key] = str(threads)
        yield
    finally:
        for key, (existed, value) in prior.items():
            if existed:
                os.environ[key] = value if value is not None else ""
            else:
                os.environ.pop(key, None)


def _load_psutil():
    """Return psutil when the accepted runtime provides it; absence is not fatal."""
    try:
        import psutil
    except ModuleNotFoundError:
        return None
    return psutil


def _ps_process_snapshot() -> dict[int, dict[str, Any]]:
    """Read one POSIX process snapshot without third-party dependencies.

    macOS and the existing Linux review environment both expose pid/ppid/rss/stat
    through ps(1). RSS is reported by ps in KiB and converted to bytes here.
    Failure to obtain a trustworthy snapshot remains fail-closed.
    """
    command = ["ps", "-axo", "pid=,ppid=,rss=,stat="]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ResourceLimitError(f"PROCESS_SNAPSHOT_FAILED:{type(exc).__name__}") from exc
    snapshot: dict[int, dict[str, Any]] = {}
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) != 4:
            raise ResourceLimitError("PROCESS_SNAPSHOT_PARSE_FAILED")
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            rss_kib = int(parts[2])
        except ValueError as exc:
            raise ResourceLimitError("PROCESS_SNAPSHOT_PARSE_FAILED") from exc
        if pid <= 0 or ppid < 0 or rss_kib < 0:
            raise ResourceLimitError("PROCESS_SNAPSHOT_VALUE_INVALID")
        snapshot[pid] = {
            "ppid": ppid,
            "rss_bytes": rss_kib * 1024,
            "status": parts[3],
        }
    if not snapshot:
        raise ResourceLimitError("PROCESS_SNAPSHOT_EMPTY")
    return snapshot


def _snapshot_descendants(snapshot: Mapping[int, Mapping[str, Any]], root_pid: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, row in snapshot.items():
        children.setdefault(int(row["ppid"]), []).append(int(pid))
    seen: set[int] = set()
    stack = [int(root_pid)]
    while stack:
        parent = stack.pop()
        if parent in seen:
            continue
        if parent in snapshot:
            seen.add(parent)
        stack.extend(children.get(parent, ()))
    return seen


def _snapshot_pid_live(snapshot: Mapping[int, Mapping[str, Any]], pid: int) -> bool:
    row = snapshot.get(int(pid))
    return row is not None and not str(row.get("status", "")).startswith("Z")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _tree_rss_bytes(root_pid: int, worker_pid: int | None, known_processes: Mapping[int, Any] | None = None) -> tuple[int, list[int], dict[int, Any]]:
    psutil = _load_psutil()
    if psutil is None:
        snapshot = _ps_process_snapshot()
        if root_pid not in snapshot:
            if _pid_exists(root_pid):
                raise ResourceLimitError(f"RSS_ROOT_MISSING_FROM_SNAPSHOT:{root_pid}")
            return 0, [], {}
        candidate_pids: set[int] = {int(root_pid)}
        if worker_pid is not None:
            worker_pid = int(worker_pid)
            if worker_pid not in snapshot:
                if _pid_exists(worker_pid):
                    raise ResourceLimitError(f"RSS_WORKER_MISSING_FROM_SNAPSHOT:{worker_pid}")
            else:
                candidate_pids.update(_snapshot_descendants(snapshot, worker_pid))
        for pid in (known_processes or {}):
            pid = int(pid)
            if pid not in snapshot and _pid_exists(pid):
                raise ResourceLimitError(f"RSS_KNOWN_PROCESS_MISSING_FROM_SNAPSHOT:{pid}")
            candidate_pids.add(pid)
        total = 0
        live_pids: list[int] = []
        retained: dict[int, Any] = {}
        for pid in sorted(candidate_pids):
            row = snapshot.get(pid)
            if row is None or str(row.get("status", "")).startswith("Z"):
                continue
            total += int(row["rss_bytes"])
            live_pids.append(pid)
            if pid != root_pid:
                retained[pid] = dict(row)
        if not live_pids:
            raise ResourceLimitError("RSS_TREE_DISAPPEARED_BEFORE_TERMINAL")
        return total, live_pids, retained

    try:
        root = psutil.Process(root_pid)
    except psutil.NoSuchProcess:
        return 0, [], {}
    processes = [root]
    if worker_pid is not None:
        try:
            worker_root = psutil.Process(worker_pid)
            processes.extend([worker_root, *worker_root.children(recursive=True)])
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as exc:
            raise ResourceLimitError(f"TREE_ENUMERATION_ACCESS_DENIED:{worker_pid}") from exc
    unique = {proc.pid: proc for proc in processes}
    for pid, proc in (known_processes or {}).items():
        if not hasattr(proc, "is_running"):
            try:
                proc = psutil.Process(pid)
            except psutil.NoSuchProcess:
                continue
        unique[int(pid)] = proc
    total = 0
    live_pids: list[int] = []
    retained: dict[int, Any] = {}
    for pid, proc in unique.items():
        try:
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                continue
            total += int(proc.memory_info().rss)
            live_pids.append(pid)
            if pid != root_pid:
                retained[pid] = proc
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise ResourceLimitError(f"RSS_ACCESS_DENIED:{pid}") from exc
    if not live_pids:
        raise ResourceLimitError("RSS_TREE_DISAPPEARED_BEFORE_TERMINAL")
    return total, sorted(live_pids), retained


def _terminate_descendants_posix(worker: mp.Process, known_processes: Mapping[int, Any]) -> dict[str, Any]:
    import signal

    access_denied: set[int] = set()
    errors: list[str] = []
    attempted: set[int] = set(int(pid) for pid in known_processes)
    try:
        snapshot = _ps_process_snapshot()
        if worker.pid is not None:
            attempted.update(_snapshot_descendants(snapshot, int(worker.pid)))
    except ResourceLimitError as exc:
        snapshot = {}
        errors.append(str(exc))
    if worker.pid is not None:
        attempted.add(int(worker.pid))

    signal_attempts: list[dict[str, Any]] = []
    if worker.pid is not None and hasattr(os, "killpg"):
        try:
            os.killpg(int(worker.pid), signal.SIGTERM)
            signal_attempts.append({"process_group_id": int(worker.pid), "signal": "TERM"})
        except ProcessLookupError:
            pass
        except PermissionError:
            access_denied.add(int(worker.pid))
            errors.append(f"PROCESS_GROUP_TERM_ACCESS_DENIED:{worker.pid}")
        except OSError as exc:
            errors.append(f"PROCESS_GROUP_TERM_FAILED:{worker.pid}:{type(exc).__name__}")
    for pid in sorted(attempted, reverse=True):
        try:
            os.kill(pid, signal.SIGTERM)
            signal_attempts.append({"pid": pid, "signal": "TERM"})
        except ProcessLookupError:
            pass
        except PermissionError:
            access_denied.add(pid)
            errors.append(f"TERMINATE_ACCESS_DENIED:{pid}")
        except OSError as exc:
            errors.append(f"TERMINATE_FAILED:{pid}:{type(exc).__name__}")
    deadline = time.monotonic() + 1.0
    remaining = set(attempted)
    while remaining and time.monotonic() < deadline:
        try:
            current = _ps_process_snapshot()
            remaining = {pid for pid in remaining if _snapshot_pid_live(current, pid)}
        except ResourceLimitError:
            remaining = {pid for pid in remaining if _pid_exists(pid)}
        if remaining:
            time.sleep(0.02)
    if remaining:
        if worker.pid is not None and hasattr(os, "killpg"):
            try:
                os.killpg(int(worker.pid), signal.SIGKILL)
                signal_attempts.append({"process_group_id": int(worker.pid), "signal": "KILL"})
            except ProcessLookupError:
                pass
            except PermissionError:
                access_denied.add(int(worker.pid))
                errors.append(f"PROCESS_GROUP_KILL_ACCESS_DENIED:{worker.pid}")
            except OSError as exc:
                errors.append(f"PROCESS_GROUP_KILL_FAILED:{worker.pid}:{type(exc).__name__}")
        for pid in sorted(remaining, reverse=True):
            try:
                os.kill(pid, signal.SIGKILL)
                signal_attempts.append({"pid": pid, "signal": "KILL"})
            except ProcessLookupError:
                pass
            except PermissionError:
                access_denied.add(pid)
                errors.append(f"KILL_ACCESS_DENIED:{pid}")
            except OSError as exc:
                errors.append(f"KILL_FAILED:{pid}:{type(exc).__name__}")
    if worker.pid is not None:
        worker.join(timeout=2.0)
    if worker.is_alive():
        try:
            worker.kill()
            worker.join(timeout=2.0)
            signal_attempts.append({"pid": worker.pid, "signal": "MP_KILL"})
        except Exception as exc:
            errors.append(f"MP_KILL_FAILED:{type(exc).__name__}")
    try:
        current = _ps_process_snapshot()
        remaining = {pid for pid in attempted if _snapshot_pid_live(current, pid)}
    except ResourceLimitError as exc:
        errors.append(str(exc))
        remaining = {pid for pid in attempted if _pid_exists(pid)}
    if worker.is_alive() and worker.pid is not None:
        remaining.add(int(worker.pid))
    return {
        "backend": "posix_ps",
        "confirmed": not remaining and not access_denied and not errors,
        "worker_pid": worker.pid,
        "worker_alive_after_termination": worker.is_alive(),
        "known_process_ids_before_termination": sorted(int(pid) for pid in known_processes),
        "remaining_process_ids": sorted(remaining),
        "access_denied_process_ids": sorted(access_denied),
        "enumeration_errors": errors,
        "termination_attempted_process_ids": sorted(attempted),
        "direct_signal_attempts": signal_attempts,
    }


def _terminate_descendants(worker: mp.Process, known_processes: Mapping[int, Any]) -> dict[str, Any]:
    psutil = _load_psutil()
    if psutil is None:
        return _terminate_descendants_posix(worker, known_processes)

    descendants: dict[int, Any] = {}
    for pid, proc in known_processes.items():
        if hasattr(proc, "terminate"):
            descendants[int(pid)] = proc
        else:
            try:
                descendants[int(pid)] = psutil.Process(pid)
            except psutil.NoSuchProcess:
                pass
    access_denied: set[int] = set()
    enumeration_errors: list[str] = []
    if worker.pid is not None:
        try:
            worker_root = psutil.Process(worker.pid)
            descendants[worker_root.pid] = worker_root
            for proc in worker_root.children(recursive=True):
                descendants[proc.pid] = proc
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            access_denied.add(worker.pid)
            enumeration_errors.append(f"CHILD_ENUMERATION_ACCESS_DENIED:{worker.pid}")
        except (psutil.Error, OSError) as exc:
            enumeration_errors.append(f"CHILD_ENUMERATION_FAILED:{worker.pid}:{type(exc).__name__}")
    process_list = list(descendants.values())
    for proc in reversed(process_list):
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            access_denied.add(proc.pid)
            enumeration_errors.append(f"TERMINATE_ACCESS_DENIED:{proc.pid}")
        except (psutil.Error, OSError) as exc:
            enumeration_errors.append(f"TERMINATE_FAILED:{proc.pid}:{type(exc).__name__}")
    try:
        _gone, alive = psutil.wait_procs(process_list, timeout=1.0)
    except (psutil.Error, OSError):
        alive = process_list
        enumeration_errors.append("WAIT_AFTER_TERMINATE_FAILED")
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            access_denied.add(proc.pid)
            enumeration_errors.append(f"KILL_ACCESS_DENIED:{proc.pid}")
        except (psutil.Error, OSError) as exc:
            enumeration_errors.append(f"KILL_FAILED:{proc.pid}:{type(exc).__name__}")
    try:
        _gone, alive_after_kill = psutil.wait_procs(alive, timeout=2.0)
    except (psutil.Error, OSError):
        alive_after_kill = alive
        enumeration_errors.append("WAIT_AFTER_KILL_FAILED")
    if worker.is_alive():
        try:
            worker.terminate()
        except (OSError, psutil.Error) as exc:
            if worker.pid is not None:
                access_denied.add(worker.pid)
                enumeration_errors.append(f"MP_TERMINATE_FAILED:{type(exc).__name__}")
        worker.join(timeout=1.0)
    if worker.is_alive():
        try:
            worker.kill()
            worker.join(timeout=2.0)
        except (OSError, psutil.Error) as exc:
            if worker.pid is not None:
                access_denied.add(worker.pid)
                enumeration_errors.append(f"MP_KILL_FAILED:{type(exc).__name__}")
    remaining: set[int] = set()
    for proc in alive_after_kill:
        try:
            if proc.status() != psutil.STATUS_ZOMBIE and proc.is_running():
                remaining.add(proc.pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            remaining.add(proc.pid)
            access_denied.add(proc.pid)
        except (psutil.Error, OSError) as exc:
            remaining.add(proc.pid)
            enumeration_errors.append(f"TERMINATION_CONFIRMATION_FAILED:{proc.pid}:{type(exc).__name__}")
    if worker.is_alive() and worker.pid is not None:
        remaining.add(worker.pid)
    return {
        "backend": "psutil",
        "confirmed": not remaining and not access_denied and not enumeration_errors,
        "worker_pid": worker.pid,
        "worker_alive_after_termination": worker.is_alive(),
        "known_process_ids_before_termination": sorted(known_processes),
        "remaining_process_ids": sorted(remaining),
        "access_denied_process_ids": sorted(access_denied),
        "enumeration_errors": enumeration_errors,
        "termination_attempted_process_ids": sorted(descendants),
    }


def _safe_terminate_descendants(
    worker: mp.Process,
    known_processes: Mapping[int, Any],
    monitor_error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    failure: str | None = None
    try:
        result = _terminate_descendants(worker, known_processes)
    except Exception as exc:
        failure = f"TERMINATION_UNEXPECTED_FAILURE:{type(exc).__name__}"
    import signal

    direct_errors: list[str] = []
    direct_signal_attempts: list[dict[str, Any]] = []
    known_pids = set(int(pid) for pid in known_processes)
    if worker.pid is not None:
        known_pids.add(int(worker.pid))
    for pid in sorted(known_pids, reverse=True):
        try:
            if worker.pid is not None and pid == worker.pid and hasattr(os, "killpg"):
                os.killpg(pid, signal.SIGTERM)
                direct_signal_attempts.append({"process_group_id": pid, "signal": "TERM"})
            else:
                os.kill(pid, signal.SIGTERM)
                direct_signal_attempts.append({"pid": pid, "signal": "TERM"})
        except ProcessLookupError:
            pass
        except PermissionError:
            direct_errors.append(f"DIRECT_TERMINATE_ACCESS_DENIED:{pid}")
        except OSError as exc:
            direct_errors.append(f"DIRECT_TERMINATE_FAILED:{pid}:{type(exc).__name__}")
    try:
        if worker.pid is not None:
            worker.join(timeout=0.5)
        psutil = _load_psutil()
        for pid in sorted(known_pids, reverse=True):
            try:
                live = False
                if psutil is not None:
                    process = psutil.Process(pid)
                    live = process.status() != psutil.STATUS_ZOMBIE and process.is_running()
                else:
                    snapshot = _ps_process_snapshot()
                    live = _snapshot_pid_live(snapshot, pid)
                if live:
                    if worker.pid is not None and pid == worker.pid and hasattr(os, "killpg"):
                        os.killpg(pid, signal.SIGKILL)
                        direct_signal_attempts.append({"process_group_id": pid, "signal": "KILL"})
                    else:
                        os.kill(pid, signal.SIGKILL)
                        direct_signal_attempts.append({"pid": pid, "signal": "KILL"})
            except ProcessLookupError:
                pass
            except PermissionError:
                direct_errors.append(f"DIRECT_KILL_ACCESS_DENIED:{pid}")
            except Exception as exc:
                direct_errors.append(f"DIRECT_KILL_CHECK_FAILED:{pid}:{type(exc).__name__}")
        if worker.pid is not None:
            worker.join(timeout=1.0)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=2.0)
            direct_signal_attempts.append({"pid": worker.pid, "signal": "MP_KILL"})
    except Exception as exc:
        direct_errors.append(f"DIRECT_WORKER_TERMINATION_FAILED:{type(exc).__name__}")
    alive = True
    try:
        alive = worker.is_alive()
    except Exception as exc:
        direct_errors.append(f"WORKER_LIVENESS_CHECK_FAILED:{type(exc).__name__}")
    if result is None:
        result = {
            "backend": "unknown",
            "confirmed": False,
            "worker_pid": worker.pid,
            "worker_alive_after_termination": alive,
            "known_process_ids_before_termination": sorted(known_processes),
            "remaining_process_ids": [],
            "access_denied_process_ids": [],
            "enumeration_errors": [],
            "termination_attempted_process_ids": sorted(known_pids),
        }
    result.setdefault("enumeration_errors", [])
    if failure:
        result["enumeration_errors"].append(failure)
    result["enumeration_errors"].extend(direct_errors)
    remaining: set[int] = set()
    access_denied: set[int] = set(result.get("access_denied_process_ids", []))
    if monitor_error:
        for marker in ("TREE_ENUMERATION_ACCESS_DENIED:", "RSS_ACCESS_DENIED:"):
            if marker in monitor_error:
                try:
                    access_denied.add(int(monitor_error.split(marker, 1)[1].split(";", 1)[0]))
                except ValueError:
                    pass
        result["enumeration_errors"].append(monitor_error)
    psutil = _load_psutil()
    if psutil is not None:
        for pid in known_pids:
            try:
                process = psutil.Process(pid)
                if process.status() != psutil.STATUS_ZOMBIE and process.is_running():
                    remaining.add(pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                access_denied.add(pid)
            except (psutil.Error, OSError) as exc:
                remaining.add(pid)
                result["enumeration_errors"].append(f"POST_TERMINATION_CHECK_FAILED:{pid}:{type(exc).__name__}")
    else:
        try:
            snapshot = _ps_process_snapshot()
            remaining.update(pid for pid in known_pids if _snapshot_pid_live(snapshot, pid))
        except ResourceLimitError as exc:
            result["enumeration_errors"].append(str(exc))
            remaining.update(pid for pid in known_pids if _pid_exists(pid))
    if alive and worker.pid is not None:
        remaining.add(int(worker.pid))
    result["remaining_process_ids"] = sorted(remaining)
    result["access_denied_process_ids"] = sorted(access_denied)
    result["worker_pid"] = worker.pid
    result["worker_alive_after_termination"] = alive
    result["known_process_ids_before_termination"] = sorted(known_processes)
    result["direct_signal_attempts"] = direct_signal_attempts
    result["termination_attempted_process_ids"] = sorted(set(result.get("termination_attempted_process_ids", [])) | known_pids)
    result["confirmed"] = not remaining and not access_denied and not result["enumeration_errors"]
    return result

def _write_json_fsync(path: Path, payload: Mapping[str, Any], *, exclusive: bool) -> None:
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open(mode) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def run_spawn_monitored(
    target: Callable[[Mapping[str, Any]], None] | None,
    payload: Mapping[str, Any],
    *,
    native_spec: Mapping[str, Any],
    native_runtime_helper_path: Path,
    wall_seconds_max: float,
    rss_bytes_max: int,
    threads: int,
    resource_trace_path: Path,
    on_worker_exit: Callable[[Mapping[str, Any]], None] | None = None,
    sample_seconds: float = 0.05,
    target_descriptor: Mapping[str, Any] | None = None,
    failure_evidence_path: Path | None = None,
    failure_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Monitor the caller plus every child from before spawn through worker exit."""
    if wall_seconds_max <= 0 or rss_bytes_max <= 0 or threads != 4:
        raise ValueError("FROZEN_RESOURCE_LIMITS_INVALID")
    if (target is None) == (target_descriptor is None):
        raise ValueError("EXACTLY_ONE_MONITORED_TARGET_REQUIRED")
    native_runtime = _load_module(native_runtime_helper_path, "f5_meta2023_native_runtime")
    native_runtime.validate_native_files(native_spec, require_macos=False)
    context_payload = dict(failure_context or {})
    source_files = dict(context_payload.get("source_files", {}))
    source_files.setdefault("resource_tree", {
        "path": str(Path(__file__).resolve()),
        "sha256": _sha256_file(Path(__file__)),
    })
    final_failure_path = Path(failure_evidence_path) if failure_evidence_path is not None else None
    child_error_path = (final_failure_path.parent / "EVALUATION_WORKER_ERROR.json") if final_failure_path is not None else None
    ctx = mp.get_context("spawn")
    process = ctx.Process(
        target=_worker_process_entry,
        args=(target, dict(target_descriptor) if target_descriptor is not None else None, dict(payload),
              str(child_error_path) if child_error_path is not None else None, source_files),
        name="f5-meta2023-candidate-worker",
    )
    trace: list[dict[str, Any]] = []
    tracked_processes: dict[int, Any] = {}
    reason: str | None = None
    termination: dict[str, Any] | None = None
    parent_pid = os.getpid()
    start = time.monotonic()
    # Both limits cover spawn startup, child verification, all input reads, the
    # one fit, batched candidate prediction, evaluation, and durable outputs.
    try:
        with native_runtime.process_local_dyld_for_spawn(str(native_spec["dyld_library_path"])), _thread_limits_for_spawn(threads):
            process.start()
    except BaseException as exc:
        if final_failure_path is not None and not final_failure_path.exists():
            write_failure_evidence_atomic(final_failure_path, {
                "schema": "F5_SAVED_EVALUATION_FAILURE_EVIDENCE_V1",
                "status": "FAILED",
                "stage": "SPAWN_START",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
                "exit_code": None,
                "exit_code_state": "PROCESS_NOT_STARTED",
                "source_files": source_files,
                "target_descriptor": dict(target_descriptor) if target_descriptor is not None else None,
                "resource_trace_path": str(Path(resource_trace_path).resolve()),
                "child_error_path": str(child_error_path.resolve()) if child_error_path is not None else None,
            })
        raise
    while True:
        elapsed = time.monotonic() - start
        try:
            rss, members, tracked_processes = _tree_rss_bytes(parent_pid, process.pid, tracked_processes)
        except ResourceLimitError as exc:
            reason = str(exc)
            rss, members = 0, []
        except Exception as exc:
            reason = f"RESOURCE_MONITOR_FAILED:{type(exc).__name__}"
            rss, members = 0, []
        trace.append({"elapsed_seconds": elapsed, "aggregate_tree_rss_bytes": int(rss), "process_ids": members})
        if reason is None and rss > rss_bytes_max:
            reason = "RSS_LIMIT_EXCEEDED"
        if reason is None and elapsed > wall_seconds_max:
            reason = "WALL_LIMIT_EXCEEDED"
        if reason is not None:
            termination = _safe_terminate_descendants(process, tracked_processes, reason)
            if not termination["confirmed"]:
                reason = f"{reason};PROCESS_TREE_TERMINATION_UNCONFIRMED"
            break
        if not process.is_alive():
            process.join()
            # Keep previously discovered grandchildren in scope if their
            # worker exits before they do and the OS reparents them.
            if not tracked_processes:
                break
        time.sleep(sample_seconds)
    terminal_elapsed = time.monotonic() - start
    peak = max((row["aggregate_tree_rss_bytes"] for row in trace), default=0)
    rss_backend = "psutil" if _load_psutil() is not None else "posix_ps"
    result = {
        "schema": "F5_META2023_RESOURCE_TRACE_V1",
        "rss_backend": rss_backend,
        "monitor_scope": "caller_plus_worker_and_all_worker_descendants",
        "monitor_start": "before_spawn_and_before_first_model_input_read",
        "monitor_stop": "after_worker_exit_or_breach_and_post_trace_fsync_cap_check",
        "wall_seconds_max": float(wall_seconds_max),
        "aggregate_rss_bytes_max": int(rss_bytes_max),
        "threads": int(threads),
        "sample_interval_seconds": float(sample_seconds),
        "rss_measurement": "sampled_process_tree_observation_not_absolute_peak",
        "rss_cap_enforcement": "terminate_on_observed_aggregate_tree_rss_exceedance",
        "hard_peak_memory_guarantee": False,
        "elapsed_seconds": float(terminal_elapsed),
        "peak_aggregate_tree_rss_bytes": int(peak),
        "worker_exitcode": process.exitcode,
        "terminal_reason": reason,
        "worker_termination": termination,
        "samples": trace,
    }
    if on_worker_exit is not None:
        try:
            on_worker_exit(dict(result))
        except BaseException as exc:
            result["terminal_reason"] = result["terminal_reason"] or f"RESULT_RECEIPT_FINALIZATION_FAILED:{type(exc).__name__}"
    # The resource evidence itself is part of the bounded result tree. Persist
    # it before declaring the monitor stopped; include caller + descendants in
    # the final resource sample as well.
    try:
        final_rss, final_members, tracked_processes = _tree_rss_bytes(parent_pid, process.pid, tracked_processes)
    except ResourceLimitError as exc:
        result["terminal_reason"] = result["terminal_reason"] or str(exc)
        final_rss, final_members = 0, []
    except Exception as exc:
        result["terminal_reason"] = result["terminal_reason"] or f"RESOURCE_MONITOR_FAILED_AFTER_WORKER_EXIT:{type(exc).__name__}"
        final_rss, final_members = 0, []
    result["samples"].append({"elapsed_seconds": time.monotonic() - start, "aggregate_tree_rss_bytes": int(final_rss), "process_ids": final_members})
    result["peak_aggregate_tree_rss_bytes"] = max(result["peak_aggregate_tree_rss_bytes"], int(final_rss))
    _write_json_fsync(Path(resource_trace_path), result, exclusive=True)
    # Check the process tree and deadline after an fsynced trace write, so trace
    # persistence itself cannot silently push a successful run over its cap.
    terminal_elapsed = time.monotonic() - start
    try:
        post_write_rss, post_write_members, tracked_processes = _tree_rss_bytes(parent_pid, process.pid, tracked_processes)
    except ResourceLimitError as exc:
        result["terminal_reason"] = result["terminal_reason"] or str(exc)
        post_write_rss, post_write_members = 0, []
    except Exception as exc:
        result["terminal_reason"] = result["terminal_reason"] or f"RESOURCE_MONITOR_FAILED_AFTER_TRACE_FSYNC:{type(exc).__name__}"
        post_write_rss, post_write_members = 0, []
    post_write_check = {
        "elapsed_seconds": float(terminal_elapsed),
        "aggregate_tree_rss_bytes": int(post_write_rss),
        "process_ids": post_write_members,
        "after_trace_fsync": True,
    }
    result["post_trace_fsync_terminal_check"] = post_write_check
    result["samples"].append(post_write_check)
    result["peak_aggregate_tree_rss_bytes"] = max(result["peak_aggregate_tree_rss_bytes"], int(post_write_rss))
    if result["terminal_reason"] is None and post_write_rss > rss_bytes_max:
        result["terminal_reason"] = "RSS_LIMIT_EXCEEDED_AFTER_TRACE_FSYNC"
    if result["terminal_reason"] is None and terminal_elapsed > wall_seconds_max:
        result["terminal_reason"] = "WALL_LIMIT_EXCEEDED_AFTER_TRACE_FSYNC"
    if result["terminal_reason"] is not None and (termination is None or not termination["confirmed"]):
        termination = _safe_terminate_descendants(process, tracked_processes, result["terminal_reason"])
        result["worker_termination"] = termination
        if not termination["confirmed"]:
            result["terminal_reason"] = f"{result['terminal_reason']};PROCESS_TREE_TERMINATION_UNCONFIRMED"
    result["elapsed_seconds"] = float(terminal_elapsed)
    _write_json_fsync(Path(resource_trace_path), result, exclusive=False)
    # This last in-memory check is returned to the runner; if it reports a
    # breach the run is non-PASS even though the trace bytes are already durable.
    final_elapsed = time.monotonic() - start
    try:
        final_rss, final_members, tracked_processes = _tree_rss_bytes(parent_pid, process.pid, tracked_processes)
    except ResourceLimitError as exc:
        result["terminal_reason"] = result["terminal_reason"] or str(exc)
        final_rss, final_members = 0, []
    except Exception as exc:
        result["terminal_reason"] = result["terminal_reason"] or f"RESOURCE_MONITOR_FAILED_AFTER_FINAL_TRACE_FSYNC:{type(exc).__name__}"
        final_rss, final_members = 0, []
    if process.pid is not None and process.pid not in final_members:
        process.join(timeout=1.0)
    result["final_post_fsync_check"] = {
        "elapsed_seconds": float(final_elapsed),
        "aggregate_tree_rss_bytes": int(final_rss),
        "process_ids": final_members,
        "after_final_trace_fsync": True,
    }
    result["peak_aggregate_tree_rss_bytes"] = max(result["peak_aggregate_tree_rss_bytes"], int(final_rss))
    result["elapsed_seconds"] = float(final_elapsed)
    if result["terminal_reason"] is None and final_rss > rss_bytes_max:
        result["terminal_reason"] = "RSS_LIMIT_EXCEEDED_AFTER_FINAL_TRACE_FSYNC"
    if result["terminal_reason"] is None and final_elapsed > wall_seconds_max:
        result["terminal_reason"] = "WALL_LIMIT_EXCEEDED_AFTER_FINAL_TRACE_FSYNC"
    if result["terminal_reason"] is not None and (termination is None or not termination["confirmed"]):
        termination = _safe_terminate_descendants(process, tracked_processes, result["terminal_reason"])
        result["worker_termination"] = termination
        if not termination["confirmed"]:
            result["terminal_reason"] = f"{result['terminal_reason']};PROCESS_TREE_TERMINATION_UNCONFIRMED"
    if result["terminal_reason"] is not None and termination is not None:
        final_worker_members = sorted(set(final_members) - {parent_pid})
        termination["final_process_tree_sample_clear"] = not final_worker_members
        termination["worker_alive_after_termination"] = process.pid in final_worker_members
        termination["remaining_process_ids"] = final_worker_members
        if not final_worker_members and not termination.get("access_denied_process_ids") and not termination.get("enumeration_errors"):
            termination["confirmed"] = True
    final_worker_exitcode = process.exitcode
    result["worker_exitcode"] = final_worker_exitcode
    if final_failure_path is not None and (result.get("terminal_reason") is not None or final_worker_exitcode not in (0, None)):
        if not final_failure_path.exists():
            child_error: dict[str, Any] | None = None
            child_error_sha256: str | None = None
            child_error_parse_error: dict[str, str] | None = None
            if child_error_path is not None and child_error_path.is_file():
                child_error_sha256 = _sha256_file(child_error_path)
                try:
                    parsed = json.loads(child_error_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        child_error = parsed
                    else:
                        child_error_parse_error = {"type": "TypeError", "message": "CHILD_ERROR_NOT_OBJECT"}
                except Exception as exc:
                    child_error_parse_error = {"type": type(exc).__name__, "message": str(exc)}
            trace_file = Path(resource_trace_path)
            stage = str(child_error.get("stage")) if child_error else "CHILD_EXIT_WITHOUT_VALID_ERROR_RECORD"
            write_failure_evidence_atomic(final_failure_path, {
                "schema": "F5_SAVED_EVALUATION_FAILURE_EVIDENCE_V1",
                "status": "FAILED",
                "stage": stage,
                "exception_type": child_error.get("exception_type") if child_error else None,
                "exception_message": child_error.get("exception_message") if child_error else None,
                "traceback": child_error.get("traceback") if child_error else None,
                "exit_code": final_worker_exitcode,
                "exit_code_state": "JOINED" if final_worker_exitcode is not None else "CANNOT_CONFIRM",
                "terminal_reason": result.get("terminal_reason"),
                "source_files": source_files,
                "target_descriptor": dict(target_descriptor) if target_descriptor is not None else None,
                "child_error_path": str(child_error_path.resolve()) if child_error_path is not None else None,
                "child_error_sha256": child_error_sha256,
                "child_error_parse_error": child_error_parse_error,
                "resource_trace_path": str(trace_file.resolve()),
                "resource_trace_sha256": _sha256_file(trace_file) if trace_file.is_file() else None,
            })
    if final_worker_exitcode is not None:
        process.close()
    return result
