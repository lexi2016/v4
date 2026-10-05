"""Persistent launchd entry for the fixed V3.5 scheduler.

This module owns only the process lifetime.  The one-shot scheduler remains
the authority for slot resolution, execution-ledger claims, and every
business workload.  Keeping that call in the same interpreter removes the
per-heartbeat import/startup cost without creating a second scheduler.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import signal
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from ops import run_v35_macos_scheduler as scheduler


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAEMON_SCHEMA = "v3_5.macos_scheduler_daemon.v1"
SAFETY_FIELDS = ("production_allowed", "buy_gate_updated", "orders_sent")
FALSE_TEXT = frozenset({"", "0", "false", "no", "off", "none", "null"})
_OUTPUT_HISTORY: list[str] = []


class DaemonConfigurationError(ValueError):
    """Raised when the launch identity or safety boundary is invalid."""


def _write_line(line: str) -> None:
    text = str(line).rstrip("\n")
    print(text, flush=True)
    _OUTPUT_HISTORY.append(text)
    if len(_OUTPUT_HISTORY) > 256:
        del _OUTPUT_HISTORY[:-256]


def _emit(payload: dict[str, Any]) -> None:
    _write_line(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def last_emitted_output() -> str:
    """Return the bounded output history for deterministic focused tests."""

    return "\n".join(_OUTPUT_HISTORY)


def _false_environment_value(name: str) -> None:
    value = os.environ.get(name)
    if value is not None and value.strip().lower() not in FALSE_TEXT:
        raise DaemonConfigurationError(f"{name} must remain false")


def _option_value(argv: Iterable[str], option: str) -> str | None:
    values = list(argv)
    for index, item in enumerate(values):
        if item == option and index + 1 < len(values):
            return values[index + 1]
        prefix = f"{option}="
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None


def _release_identity(argv: Iterable[str]) -> str:
    requested = _option_value(argv, "--release-id")
    release_id = requested or os.environ.get("V35_RELEASE_ID", "")
    release_id = str(release_id).strip()
    if not release_id or "/" in release_id or "\\" in release_id:
        raise DaemonConfigurationError("V35_RELEASE_ID is missing or path-like")
    configured = os.environ.get("V35_RELEASE_ID")
    if configured and configured != release_id:
        raise DaemonConfigurationError("--release-id does not match V35_RELEASE_ID")
    for name in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        _false_environment_value(name)
    for name in ("production_allowed", "buy_gate_updated", "orders_sent"):
        _false_environment_value(name)
    return release_id


def _as_shanghai(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def _minute_key(moment: datetime) -> str:
    return _as_shanghai(moment).strftime("%Y-%m-%dT%H:%M")


def _seconds_to_next_minute(moment: datetime) -> float:
    local = _as_shanghai(moment)
    next_minute = (local + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return max(0.001, (next_minute - local).total_seconds())


def _bounded_error(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}".replace("\n", " ")
    return text[:600]


def _parse_scheduler_output(text: str) -> dict[str, Any] | None:
    last_object: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            last_object = value
    return last_object


def _validate_scheduler_result(payload: dict[str, Any], release_id: str) -> None:
    if not isinstance(payload.get("status"), str) or not payload["status"]:
        raise DaemonConfigurationError("one-shot result has no status")
    result_release = payload.get("release_id")
    if result_release is not None and str(result_release) != release_id:
        raise DaemonConfigurationError("one-shot result release identity mismatch")
    for field in SAFETY_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            unsafe = value.strip().lower() not in FALSE_TEXT
        else:
            unsafe = bool(value)
        if unsafe:
            raise DaemonConfigurationError(f"one-shot result {field} is not false")


def _install_signal_handlers(stop_event: threading.Event) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _run_one_cycle(
    scheduler_argv: list[str],
    *,
    scheduler_main: Callable[[list[str]], int],
    release_id: str,
    cycle_number: int,
    minute: str,
) -> bool:
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            return_code = scheduler_main(list(scheduler_argv))
    except SystemExit as error:
        raise DaemonConfigurationError(
            f"one-shot scheduler terminated during configuration: {error.code}"
        ) from error
    except Exception as error:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_CYCLE_FAILED",
                "release_id": release_id,
                "pid": os.getpid(),
                "cycle": cycle_number,
                "minute": minute,
                "error": _bounded_error(error),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return False

    scheduler_output = captured.getvalue()
    for line in scheduler_output.splitlines():
        if line.strip():
            _write_line(line)
    payload = _parse_scheduler_output(scheduler_output)
    if payload is None:
        try:
            normalized_return_code = int(return_code)
        except (TypeError, ValueError):
            normalized_return_code = 1
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_CYCLE_FAILED",
                "release_id": release_id,
                "pid": os.getpid(),
                "cycle": cycle_number,
                "minute": minute,
                "error": "scheduler emitted no JSON result",
                "return_code": normalized_return_code,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return False
    try:
        _validate_scheduler_result(payload, release_id)
    except DaemonConfigurationError:
        raise
    try:
        normalized_return_code = int(return_code)
    except (TypeError, ValueError):
        normalized_return_code = 1
    _emit(
        {
            "schema_version": DAEMON_SCHEMA,
            "status": "DAEMON_CYCLE",
            "release_id": release_id,
            "pid": os.getpid(),
            "cycle": cycle_number,
            "minute": minute,
            "result_status": str(payload.get("status") or "UNKNOWN"),
            "return_code": normalized_return_code,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    return True


def run_daemon(
    scheduler_argv: list[str],
    *,
    scheduler_main: Callable[[list[str]], int] = scheduler.main,
    clock: Callable[[], datetime] | None = None,
    stop_event: threading.Event | None = None,
    install_signals: bool = True,
    poll_interval_seconds: float = 1.0,
    heartbeat_seconds: float = 60.0,
) -> int:
    """Run the persistent minute loop around the existing one-shot entry.

    ``clock`` and ``scheduler_main`` are dependency-injection seams for the
    offline focused tests.  Production uses ``datetime.now`` and the real
    one-shot scheduler, so all claims and receipts continue through the
    existing execution ledger.
    """

    _OUTPUT_HISTORY.clear()
    if any(
        argument == "--repair-expected-old-input-sha256"
        or argument.startswith("--repair-expected-old-input-sha256=")
        for argument in scheduler_argv
    ):
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_FATAL",
                "error": "REPAIR_AUTH_FORBIDDEN_IN_DAEMON",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 2
    event = stop_event or threading.Event()
    now = clock or (lambda: datetime.now(SHANGHAI))
    if poll_interval_seconds <= 0 or heartbeat_seconds <= 0:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_FATAL",
                "error": "daemon wait intervals must be positive",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 2
    try:
        release_id = _release_identity(scheduler_argv)
    except DaemonConfigurationError as error:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_FATAL",
                "error": _bounded_error(error),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 2

    previous_handlers: dict[int, Any] = {}
    if install_signals:
        try:
            previous_handlers = _install_signal_handlers(event)
        except ValueError as error:
            _emit(
                {
                    "schema_version": DAEMON_SCHEMA,
                    "status": "DAEMON_FATAL",
                    "error": _bounded_error(error),
                    "release_id": release_id,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
            return 2

    cycles = 0
    last_minute: str | None = None
    try:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_READY",
                "release_id": release_id,
                "pid": os.getpid(),
                "heartbeat_seconds": heartbeat_seconds,
                "timezone": "Asia/Shanghai",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "started_at": _as_shanghai(now()).isoformat(),
            }
        )
        while not event.is_set():
            moment = _as_shanghai(now())
            minute = _minute_key(moment)
            if minute != last_minute:
                last_minute = minute
                cycles += 1
                try:
                    _run_one_cycle(
                        scheduler_argv,
                        scheduler_main=scheduler_main,
                        release_id=release_id,
                        cycle_number=cycles,
                        minute=minute,
                    )
                except DaemonConfigurationError as error:
                    _emit(
                        {
                            "schema_version": DAEMON_SCHEMA,
                            "status": "DAEMON_FATAL",
                            "release_id": release_id,
                            "pid": os.getpid(),
                            "cycle": cycles,
                            "minute": minute,
                            "error": _bounded_error(error),
                            "production_allowed": False,
                            "buy_gate_updated": False,
                            "orders_sent": False,
                        }
                    )
                    return 2
            wait_for = min(
                float(poll_interval_seconds), _seconds_to_next_minute(moment)
            )
            event.wait(max(0.001, wait_for))
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "DAEMON_STOPPED",
                "release_id": release_id,
                "pid": os.getpid(),
                "cycles": cycles,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0
    finally:
        if previous_handlers:
            _restore_signal_handlers(previous_handlers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the persistent V3.5 scheduler daemon")
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=float(os.environ.get("V35_DAEMON_POLL_INTERVAL_SECONDS", "1")),
        help="internal stop/wakeup check interval; business slots remain scheduler-owned",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(os.environ.get("V35_DAEMON_HEARTBEAT_SECONDS", "60")),
    )
    daemon_args, scheduler_argv = parser.parse_known_args(argv)
    return run_daemon(
        scheduler_argv,
        poll_interval_seconds=daemon_args.poll_interval_seconds,
        heartbeat_seconds=daemon_args.heartbeat_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DAEMON_SCHEMA",
    "DaemonConfigurationError",
    "last_emitted_output",
    "main",
    "run_daemon",
]
