"""Bounded POSIX runner for repeated V4 runtime graph collection."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from infrastructure.runtime_graph.contracts import GraphStatus
from infrastructure.runtime_graph.http_client import validate_api_base


DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_DURATION_SECONDS = 59400
DEFAULT_API_BASE = "http://127.0.0.1:8873"
RESULT_SCHEMA = "v3_runtime_graph_collector_result.v1"
RUNNER_RESULT_SCHEMA = "v3_5_runtime_graph_collector_runner_result.v1"
RECEIPT_SCHEMA = "v3_5_collector_receipt.v1"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
MAX_CHILD_OUTPUT = 1024 * 1024
MAX_DURATION_SECONDS = 24 * 60 * 60
MAX_CHILD_TIMEOUT_SECONDS = 60 * 60
MAX_INTERVAL_SECONDS = 60 * 60
_COLLECTOR_MODULE = "ops.collect_runtime_graph"
_STATUS_BY_RETURNCODE = {
    0: {"PASS", "DEGRADED", "RUNNING", "NOT_DUE", "SKIPPED_EXPECTED"},
    1: {"FAIL"},
    2: {"EVIDENCE_GAP"},
}


class CollectorLockHeld(RuntimeError):
    pass


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_DATE = re.compile(r"^\d{8}$")


def _path_text(value: Path | str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE") from error
    if isinstance(text, bytes) or "\\" in text or _WINDOWS_DRIVE.match(text):
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    return text


def _assert_no_symlink_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")


def _is_documents_candidate_path(path: Path) -> bool:
    base = Path("/Users/lexi/Documents/Codex/2026-08-13")
    try:
        relative = path.relative_to(base)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0].startswith("v35-stage-selection-")


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _validate_data_root(value: Path | str) -> Path:
    text = os.path.expanduser(_path_text(value))
    path = Path(os.path.abspath(text))
    if {part.casefold() for part in path.parts} & {"desktop", "windows"}:
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    _assert_no_symlink_ancestors(path)
    formal = Path.home() / "Library" / "Application Support" / "com.lexi.v4.local" / "state" / "data"
    if not (_within(path, formal) or _is_documents_candidate_path(path)):
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    return path


def _valid_business_date(value: Any) -> str:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise ValueError("DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("DATE_INVALID") from error
    return value


def _bounded_float(value: Any, name: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name}_INVALID")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0 or parsed > maximum:
        raise ValueError(f"{name}_INVALID")
    return parsed


class CollectorLock:
    """Single-instance POSIX lock released by the kernel on process exit."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: Any = None

    def acquire(self) -> None:
        if os.name == "nt":
            raise CollectorLockHeld("POSIX_ONLY")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise CollectorLockHeld("COLLECTOR_LOCK_HELD") from error
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "CollectorLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _bounded(value: str | None, limit: int = MAX_CHILD_OUTPUT) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + f"\n[truncated,total={len(text)}]"


def _default_child_runner(repo_root: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run_child(command: list[str], *, cwd: Path, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=False,
            cwd=cwd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    return run_child


def _child_command(*, business_date: str, data_root: Path, api_base: str = DEFAULT_API_BASE) -> list[str]:
    return [
        sys.executable,
        "-m",
        _COLLECTOR_MODULE,
        "--date",
        business_date,
        "--data-root",
        str(data_root),
        "--api-base",
        validate_api_base(api_base),
    ]


def _validate_child_result(completed: subprocess.CompletedProcess[str], *, business_date: str) -> tuple[str, dict[str, Any]]:
    _valid_business_date(business_date)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ValueError("CHILD_RESULT_INVALID")
    if len(stdout) > MAX_CHILD_OUTPUT or len(stderr) > MAX_CHILD_OUTPUT:
        raise ValueError("CHILD_OUTPUT_TOO_LARGE")
    try:
        payload = json.loads(stdout.strip())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("CHILD_RESULT_INVALID") from error
    if not isinstance(payload, dict):
        raise ValueError("CHILD_RESULT_INVALID")
    status = str(payload.get("status") or "")
    if (
        payload.get("schema_version") != RESULT_SCHEMA
        or payload.get("business_date") != business_date
        or status not in {item.value for item in GraphStatus}
        or payload.get("snapshot_published") is not True
        or payload.get("events_recorded") is not True
        or status not in _STATUS_BY_RETURNCODE.get(completed.returncode, set())
        or any(type(payload.get(name)) is not bool or payload.get(name) is not False for name in SAFETY_FLAGS)
    ):
        raise ValueError("CHILD_RESULT_INVALID")
    return status, payload


def _receipt(*, iteration: int, outcome: str, status: str, started_at: str, ended_at: str, returncode: int | None, duration_seconds: float, detail: str = "") -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "iteration": iteration,
        "outcome": outcome,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "child_return_code": returncode,
        "duration_seconds": round(duration_seconds, 3),
        "detail": detail,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _publish_receipt(data_root: Path, payload: dict[str, Any]) -> None:
    root = _validate_data_root(data_root)
    destination = root / "runtime_graph" / "state" / "collector_receipt.json"
    _assert_no_symlink_ancestors(destination.parent)
    if destination.is_symlink():
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write((json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_collector(
    *,
    data_root: Path,
    business_date: str,
    api_base: str = DEFAULT_API_BASE,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    duration_seconds: int | None = None,
    iterations: int | None = None,
    child_timeout_seconds: float = 300.0,
    child_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> tuple[int, dict[str, Any]]:
    if os.name == "nt":
        raise ValueError("POSIX_ONLY")
    business_date = _valid_business_date(business_date)
    api_base = validate_api_base(api_base)
    interval_seconds = _bounded_float(interval_seconds, "COLLECTOR_INTERVAL", maximum=MAX_INTERVAL_SECONDS)
    child_timeout_seconds = _bounded_float(child_timeout_seconds, "COLLECTOR_TIMEOUT", maximum=MAX_CHILD_TIMEOUT_SECONDS)
    if duration_seconds is not None:
        duration_seconds = _bounded_float(duration_seconds, "COLLECTOR_DURATION", maximum=MAX_DURATION_SECONDS)
    elif iterations is None:
        raise ValueError("COLLECTOR_DURATION_INVALID")
    if iterations is not None and iterations < 1:
        raise ValueError("COLLECTOR_ITERATIONS_INVALID")
    root = _validate_data_root(data_root)
    repo_root = Path(__file__).resolve().parents[1]
    runner = child_runner or _default_child_runner(repo_root)
    final: dict[str, Any] = {
        "schema_version": RUNNER_RESULT_SCHEMA,
        "business_date": business_date,
        "status": "PASS",
        "iterations": 0,
        "last_outcome": "STARTED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    lock = CollectorLock(root / "runtime_graph" / "state" / "collector.lock")
    try:
        lock.acquire()
    except CollectorLockHeld:
        final.update(status="CONCURRENCY_SKIPPED")
        return 0, final
    started = time.monotonic()
    deadline = started + duration_seconds if duration_seconds is not None else None
    next_launch = started
    iteration = 0
    worst = 0
    try:
        while (iterations is None or iteration < iterations) and (deadline is None or time.monotonic() < deadline):
            delay = max(0.0, next_launch - time.monotonic())
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - time.monotonic()))
            if delay:
                time.sleep(delay)
            if deadline is not None and time.monotonic() >= deadline:
                break
            started_at = datetime.now(UTC).isoformat(timespec="seconds")
            monotonic = time.monotonic()
            outcome, status, detail, returncode = "FAIL", "FAIL", "", None
            try:
                completed = runner(
                    _child_command(business_date=business_date, data_root=root, api_base=api_base),
                    cwd=repo_root,
                    timeout_seconds=child_timeout_seconds,
                )
                status, payload = _validate_child_result(completed, business_date=business_date)
                del payload
                outcome, returncode = status, int(completed.returncode)
            except subprocess.TimeoutExpired:
                outcome, detail = "TIMEOUT", "child timed out"
            except (OSError, ValueError) as error:
                detail = f"{type(error).__name__}:{_bounded(str(error))}"
            iteration += 1
            _publish_receipt(root, _receipt(
                iteration=iteration,
                outcome=outcome,
                status=status,
                started_at=started_at,
                ended_at=datetime.now(UTC).isoformat(timespec="seconds"),
                returncode=returncode,
                duration_seconds=max(0.0, time.monotonic() - monotonic),
                detail=detail,
            ))
            final.update(iterations=iteration, last_outcome=outcome)
            if outcome == "FAIL" or status == "FAIL" or outcome == "TIMEOUT":
                worst = 1
                final["status"] = "FAIL"
                if outcome == "FAIL":
                    return 1, final
            elif outcome == "EVIDENCE_GAP":
                worst = max(worst, 2)
            next_launch = monotonic + float(interval_seconds)
    finally:
        lock.release()
    if iteration == 0:
        final.update(status="FAIL", reason="NO_ITERATIONS")
        return 1, final
    final["status"] = "FAIL" if worst == 1 else "EVIDENCE_GAP" if worst == 2 else "PASS"
    return worst, final


def _positive(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name}_INVALID") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"{name}_INVALID")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V4 runtime graph collector")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--interval-seconds", type=lambda value: _positive(value, "INTERVAL_SECONDS"), default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--duration-seconds", type=lambda value: _positive(value, "DURATION_SECONDS"), default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--iterations", type=lambda value: _positive(value, "ITERATIONS"))
    parser.add_argument("--child-timeout-seconds", type=float, default=300.0)
    try:
        args = parser.parse_args(argv)
        code, result = run_collector(
            data_root=args.data_root,
            business_date=args.date,
            api_base=args.api_base,
            interval_seconds=args.interval_seconds,
            duration_seconds=args.duration_seconds,
            iterations=args.iterations,
            child_timeout_seconds=args.child_timeout_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
        return code
    except Exception as error:
        print(json.dumps({
            "schema_version": RUNNER_RESULT_SCHEMA,
            "status": "FAIL",
            "reason": f"{type(error).__name__}:{error}",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
