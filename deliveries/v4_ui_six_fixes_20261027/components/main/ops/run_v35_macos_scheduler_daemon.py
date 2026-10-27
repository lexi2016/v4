"""Persistent launchd entry for the fixed V3.5 scheduler.

This module owns only the process lifetime.  The one-shot scheduler remains
the authority for slot resolution, execution-ledger claims, and every
business workload.  Keeping that call in the same interpreter removes the
per-heartbeat import/startup cost without creating a second scheduler.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import threading
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from ops import run_v35_macos_scheduler as scheduler


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAEMON_SCHEMA = "v3_5.macos_scheduler_daemon.v1"
SAFETY_FIELDS = ("production_allowed", "buy_gate_updated", "orders_sent")
FALSE_TEXT = frozenset({"", "0", "false", "no", "off", "none", "null"})
_OUTPUT_HISTORY: list[str] = []
ANNOUNCEMENT_BINDING_SCHEMA = "v4.manager_research.announcement_binding.v1"
ANNOUNCEMENT_BINDING_ENV = "V4_MANAGER_ANNOUNCEMENT_BINDING"
ANNOUNCEMENT_APP_ENV = "V4_MANAGER_ANNOUNCEMENT_APP_ROOT"
ANNOUNCEMENT_PYTHON_ENV = "V4_MANAGER_ANNOUNCEMENT_PYTHON"
ANNOUNCEMENT_PYTHON_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256"
ANNOUNCEMENT_CYCLE_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256"
ANNOUNCEMENT_PLAN_CANARY_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256"
ANNOUNCEMENT_CYCLE_RELATIVE = "ops/run_manager_announcement_cycle.py"
ANNOUNCEMENT_CHILD_WALL_SECONDS = 50.0
ANNOUNCEMENT_CHILD_KILL_GRACE_SECONDS = 1.0
PDF_QUEUE_EMPTY_FALLBACK_SECONDS = 300.0
PDF_QUEUE_TICK_SECONDS = 90
PDF_QUEUE_CHILD_WALL_SECONDS = 150.0
PDF_QUEUE_CHILD_KILL_GRACE_SECONDS = 2.0


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


def _emit_announcement(payload: dict[str, Any]) -> None:
    """Keep hook logs out of the scheduler's process-wide stdout capture."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), file=sys.stderr, flush=True)


def _pdf_queue_safe_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "schema_version", "status", "document_status", "document_id", "trade_date", "slot",
        "source_run_id", "processed_document_count", "pending_task_count", "retry_wait_count",
        "next_retry_seconds", "retry_after_seconds", "processed_page_count", "page_count",
        "last_error_code", "reason_code", "failure_class", "pdf_sha256", "pages_file_sha256",
        "done_total", "partial_total", "failed_total", "pending_total", "return_code", "runner_status",
        "admission", "ocr_invoked", "queue_mutated",
    )
    return {key: payload[key] for key in fields if key in payload}
def _emit_pdf_queue(payload: dict[str, Any]) -> None:
    """Keep PDF worker receipts separate from the scheduler's captured JSON."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), file=sys.stderr, flush=True)

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


def _sha256_file(path: Path, *, maximum_bytes: int = 128 * 1024 * 1024) -> str:
    if not path.is_file():
        raise DaemonConfigurationError("announcement pinned file is missing or oversized")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > maximum_bytes:
                raise DaemonConfigurationError("announcement pinned file is missing or oversized")
            digest.update(chunk)
    return digest.hexdigest()


def _read_bounded_bytes(path: Path, maximum_bytes: int) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise DaemonConfigurationError("announcement file is oversized")
    return payload


def _exact_path(value: Any, *, allow_leaf_symlink: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise DaemonConfigurationError("announcement path is missing")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or os.path.normpath(value) != value:
        raise DaemonConfigurationError("announcement path is not absolute and normalized")
    if allow_leaf_symlink:
        if path.parent.resolve(strict=True) != path.parent:
            raise DaemonConfigurationError("announcement executable parent is not exact")
    elif path.resolve(strict=False) != path:
        raise DaemonConfigurationError("announcement path resolves through a symlink")
    return path


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DaemonConfigurationError("announcement binding has duplicate fields")
        result[key] = value
    return result


def _load_announcement_binding(environment: dict[str, str]) -> dict[str, Any] | None:
    binding_text = environment.get(ANNOUNCEMENT_BINDING_ENV, "").strip()
    if not binding_text:
        return None
    expected = {
        ANNOUNCEMENT_APP_ENV: environment.get(ANNOUNCEMENT_APP_ENV, "").strip(),
        ANNOUNCEMENT_PYTHON_ENV: environment.get(ANNOUNCEMENT_PYTHON_ENV, "").strip(),
        ANNOUNCEMENT_PYTHON_SHA_ENV: environment.get(ANNOUNCEMENT_PYTHON_SHA_ENV, "").strip(),
        ANNOUNCEMENT_CYCLE_SHA_ENV: environment.get(ANNOUNCEMENT_CYCLE_SHA_ENV, "").strip(),
    }
    if any(not value for value in expected.values()):
        raise DaemonConfigurationError("announcement environment pins are incomplete")

    binding_path = _exact_path(binding_text)
    if not binding_path.is_file() or binding_path.stat().st_size > 1024 * 1024:
        raise DaemonConfigurationError("announcement binding is missing or oversized")
    binding_bytes = _read_bounded_bytes(binding_path, 1024 * 1024)
    try:
        binding = json.loads(binding_bytes, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DaemonConfigurationError("announcement binding JSON is invalid") from error
    if not isinstance(binding, dict):
        raise DaemonConfigurationError("announcement binding is not an object")
    if (
        binding.get("schema_version") != ANNOUNCEMENT_BINDING_SCHEMA
        or type(binding.get("enabled")) is not bool
        or binding.get("policy_status") != "PROPOSAL_ONLY"
        or binding.get("policy") not in {"BALANCED_V1", "LOW_LOAD_V1"}
        or binding.get("production_allowed") is not False
        or binding.get("buy_gate_updated") is not False
        or binding.get("orders_sent") is not False
        or binding.get("research_only") is not True
    ):
        raise DaemonConfigurationError("announcement binding contract is unsafe or unsupported")
    plan_only=binding.get("plan_material_refresh_only",False)
    collection=binding.get("announcement_collection_enabled",True)
    if type(plan_only) is not bool or type(collection) is not bool or (plan_only and collection):
        raise DaemonConfigurationError("plan-only announcement binding contract is invalid")

    app_root = _exact_path(expected[ANNOUNCEMENT_APP_ENV])
    if not app_root.is_dir() or binding.get("app_root") != str(app_root):
        raise DaemonConfigurationError("announcement app root does not match its explicit pin")
    python_text = expected[ANNOUNCEMENT_PYTHON_ENV]
    python_path = _exact_path(python_text, allow_leaf_symlink=True)
    if binding.get("python") != python_text:
        raise DaemonConfigurationError("announcement interpreter does not match its explicit pin")
    try:
        resolved_python = python_path.resolve(strict=True)
    except OSError as error:
        raise DaemonConfigurationError("announcement interpreter is missing") from error
    if (
        not resolved_python.is_file()
        or not os.access(python_path, os.X_OK)
        or binding.get("python_resolved") != str(resolved_python)
    ):
        raise DaemonConfigurationError("announcement interpreter identity is invalid")
    python_sha = expected[ANNOUNCEMENT_PYTHON_SHA_ENV]
    if (
        len(python_sha) != 64
        or any(character not in "0123456789abcdef" for character in python_sha)
        or binding.get("python_sha256") != python_sha
        or _sha256_file(resolved_python) != python_sha
    ):
        raise DaemonConfigurationError("announcement interpreter SHA does not match")

    cycle_path = app_root / ANNOUNCEMENT_CYCLE_RELATIVE
    cycle_sha = expected[ANNOUNCEMENT_CYCLE_SHA_ENV]
    files = binding.get("files")
    if (
        not isinstance(files, dict)
        or len(cycle_sha) != 64
        or any(character not in "0123456789abcdef" for character in cycle_sha)
        or files.get(ANNOUNCEMENT_CYCLE_RELATIVE) != cycle_sha
        or not cycle_path.is_file()
        or cycle_path.resolve(strict=True) != cycle_path
        or _sha256_file(cycle_path) != cycle_sha
    ):
        raise DaemonConfigurationError("announcement cycle file SHA does not match")

    activation = binding.get("activation_receipt")
    if binding["enabled"] and not plan_only:
        if not isinstance(activation, dict):
            raise DaemonConfigurationError("enabled announcement binding has no activation receipt")
        receipt_sha = activation.get("sha256")
        if (
            not isinstance(receipt_sha, str)
            or len(receipt_sha) != 64
            or any(character not in "0123456789abcdef" for character in receipt_sha)
        ):
            raise DaemonConfigurationError("enabled announcement receipt pin is invalid")
        receipt_path = _exact_path(activation.get("path"))
        if _sha256_file(receipt_path, maximum_bytes=8 * 1024 * 1024) != receipt_sha:
            raise DaemonConfigurationError("enabled announcement receipt SHA does not match")
    elif activation is not None:
        raise DaemonConfigurationError("disabled announcement binding has an unexpected receipt")

    canary_sha_env=environment.get(ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,"").strip()
    canary_ref=binding.get("plan_activation_receipt")
    if plan_only:
        if (not binding["enabled"] or not isinstance(binding.get("plan_material_refresh"),dict)
                or binding["plan_material_refresh"].get("enabled") is not True
                or binding["plan_material_refresh"].get("status")!="PROPOSAL_ONLY"
                or binding.get("activation_receipt") is not None
                or not isinstance(canary_ref,dict)):
            raise DaemonConfigurationError("plan-only binding requires its own enabled plan canary")
        canary_path=_exact_path(canary_ref.get("path"))
        if (len(canary_sha_env)!=64 or any(c not in "0123456789abcdef" for c in canary_sha_env)
                or canary_ref.get("sha256")!=canary_sha_env
                or _sha256_file(canary_path,maximum_bytes=1024*1024)!=canary_sha_env):
            raise DaemonConfigurationError("plan canary SHA does not match its explicit pin")
        try:
            canary=json.loads(_read_bounded_bytes(canary_path,1024*1024))
        except (UnicodeDecodeError,json.JSONDecodeError) as error:
            raise DaemonConfigurationError("plan canary JSON is invalid") from error
        if (not isinstance(canary,dict)
                or canary.get("schema_version")!="manager_daily_chain.plan_refresh_owner_evidence.v2"
                or canary.get("status")!="PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
                or canary.get("app_root")!=str(app_root)
                or canary.get("candidate_binding_app_root")!=str(app_root)
                or not isinstance(canary.get("owner_execution_app_root"),str)
                or canary.get("execution_mode")!="HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK"
                or canary.get("hook_executed") is not False
                or canary.get("manager_state_root")!=binding.get("manager_state_root")
                or canary.get("plan_material_refresh_only") is not True
                or canary.get("announcement_collection_enabled") is not False
                or canary.get("announcement_network_requests")!=0
                or canary.get("research_only") is not True
                or canary.get("production_allowed") is not False
                or canary.get("buy_gate_updated") is not False
                or canary.get("orders_sent") is not False):
            raise DaemonConfigurationError("plan canary contract does not match this binding")
    elif canary_ref is not None or canary_sha_env:
        raise DaemonConfigurationError("disabled plan canary has an unexpected receipt")

    return {
        "binding_path": binding_path,
        "binding_sha256": hashlib.sha256(binding_bytes).hexdigest(),
        "app_root": app_root,
        "python_path": python_path,
        "python_sha256": python_sha,
        "cycle_path": cycle_path,
        "cycle_sha256": cycle_sha,
        "policy": binding["policy"],
        "enabled": binding["enabled"],
        "plan_material_refresh_only":plan_only,
    }


def _announcement_child_environment(source: dict[str, str]) -> dict[str, str]:
    names = ("LANG", "LC_ALL", "TZ", "TMPDIR")
    environment = {name: source[name] for name in names if source.get(name)}
    environment.update(
        PRODUCTION_ALLOWED="false",
        BUY_GATE_UPDATED="false",
        ORDERS_SENT="false",
        PYTHONNOUSERSITE="1",
    )
    return environment


def _announcement_due(moment: datetime, policy: str) -> bool:
    local = _as_shanghai(moment)
    minute_of_day = local.hour * 60 + local.minute
    if not 7 * 60 <= minute_of_day < 23 * 60:
        return False
    if 15 * 60 + 19 <= minute_of_day < 15 * 60 + 40:
        return False
    if policy == "LOW_LOAD_V1":
        return int(local.timestamp()) // 60 % 2 == 0
    return policy == "BALANCED_V1"


class AnnouncementCycleHook:
    def __init__(self, identity: dict[str, Any], *, clock: Callable[[], datetime] | None = None,
                 popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen, poll_seconds: float = 0.25,
                 wall_seconds: float = ANNOUNCEMENT_CHILD_WALL_SECONDS,
                 kill_grace_seconds: float = ANNOUNCEMENT_CHILD_KILL_GRACE_SECONDS) -> None:
        self.identity = identity
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.popen_factory = popen_factory
        self.poll_seconds = max(0.01, float(poll_seconds))
        self.wall_seconds = max(0.01, float(wall_seconds))
        self.kill_grace_seconds = max(0.01, float(kill_grace_seconds))
        self.cancel = threading.Event()
        self.last_minute: str | None = None
        self.thread = threading.Thread(target=self._run, name="v35-announcement-cycle-hook", daemon=True)

    @classmethod
    def from_environment(cls, *, clock: Callable[[], datetime] | None = None,
                         popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
                         poll_seconds: float = 0.25, wall_seconds: float = ANNOUNCEMENT_CHILD_WALL_SECONDS,
                         kill_grace_seconds: float = ANNOUNCEMENT_CHILD_KILL_GRACE_SECONDS,
                         start: bool = True) -> "AnnouncementCycleHook | None":
        try:
            identity = _load_announcement_binding(dict(os.environ))
        except DaemonConfigurationError:
            raise
        except Exception as error:
            raise DaemonConfigurationError("announcement binding could not be validated") from error
        if identity is None or not identity["enabled"]:
            return None
        hook = cls(identity, clock=clock, popen_factory=popen_factory, poll_seconds=poll_seconds,
                   wall_seconds=wall_seconds, kill_grace_seconds=kill_grace_seconds)
        if start:
            hook.thread.start()
        return hook

    def _mark_minute(self, moment: datetime) -> str:
        minute = _minute_key(moment)
        self.last_minute = minute
        return minute

    def _binding_revoked(self) -> bool:
        try:
            path = self.identity["binding_path"]
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                return True
            return hashlib.sha256(_read_bounded_bytes(path, 1024 * 1024)).hexdigest() != self.identity["binding_sha256"]
        except Exception:
            return True

    def _signal_owned_group(self, child: subprocess.Popen, signum: int) -> None:
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass
        except OSError as error:
            _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_SIGNAL_FAILED", "error": _bounded_error(error)})

    def _finish_child(self, child: subprocess.Popen, reason: str) -> None:
        try:
            finished = child.poll() is not None
        except Exception:
            finished = False
        if finished:
            try:
                child.wait(timeout=0)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return
        self._signal_owned_group(child, signal.SIGTERM)
        try:
            child.wait(timeout=self.kill_grace_seconds)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
        self._signal_owned_group(child, signal.SIGKILL)
        try:
            child.wait(timeout=self.kill_grace_seconds)
        except (subprocess.TimeoutExpired, OSError):
            _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_REAP_UNCONFIRMED", "reason": reason})

    def _run_child(self) -> None:
        identity = self.identity
        command = [
            str(identity["python_path"]),
            "-I",
            "-B",
            str(identity["cycle_path"]),
            "--binding",
            str(identity["binding_path"]),
        ]
        try:
            child = self.popen_factory(command, cwd=str(identity["app_root"]),
                env=_announcement_child_environment(dict(os.environ)), stdin=subprocess.DEVNULL,
                stdout=None, stderr=None, start_new_session=True, close_fds=True)
        except Exception as error:
            _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_START_FAILED", "error": _bounded_error(error)})
            return

        reason = "EXITED"
        deadline = time.monotonic() + self.wall_seconds
        while True:
            try:
                return_code = child.poll()
            except Exception as error:
                reason = "POLL_FAILED"
                _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_POLL_FAILED", "error": _bounded_error(error)})
                break
            if return_code is not None:
                try:
                    child.wait(timeout=0)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_EXITED", "return_code": return_code})
                return

            try:
                self._mark_minute(self.clock())
                if self.cancel.is_set():
                    reason = "CANCELLED"
                elif self._binding_revoked():
                    reason = "BINDING_REVOKED"
                elif time.monotonic() >= deadline:
                    reason = "TIMEOUT"
            except Exception as error:
                reason = "HOOK_CONTROL_FAILED"
                _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_HOOK_ERROR", "error": _bounded_error(error)})
            if reason != "EXITED":
                break
            self.cancel.wait(min(self.poll_seconds, max(0.001, deadline - time.monotonic())))
        self._finish_child(child, reason)
        _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_CHILD_STOPPED", "reason": reason})

    def _run(self) -> None:
        while not self.cancel.is_set():
            try:
                moment = _as_shanghai(self.clock())
                minute = _minute_key(moment)
                if minute != self.last_minute:
                    self.last_minute = minute
                    if _announcement_due(moment, self.identity["policy"]):
                        if self._binding_revoked():
                            _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_BINDING_REVOKED"})
                            self.cancel.set()
                        else:
                            self._run_child()
            except Exception as error:
                _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_HOOK_ERROR", "error": _bounded_error(error)})
            self.cancel.wait(self.poll_seconds)

    def stop(self, *, join_seconds: float = 3.0) -> None:
        self.cancel.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=max(0.0, join_seconds))
            if self.thread.is_alive():
                _emit_announcement({"schema_version": DAEMON_SCHEMA, "status": "ANNOUNCEMENT_HOOK_JOIN_TIMEOUT"})


class PdfQueueDrainHook:
    """Drain the owned PDF index in a child without occupying scheduler work."""

    def __init__(
        self,
        *,
        app_root: Path,
        data_root: Path,
        python_path: Path,
        cycle_active: threading.Event | None = None,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        poll_seconds: float = 0.25,
        wall_seconds: float = PDF_QUEUE_CHILD_WALL_SECONDS,
        idle_seconds: float = 60.0,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app_root = app_root
        self.data_root = data_root
        self.python_path = python_path
        self.cycle_active = cycle_active or threading.Event()
        self.popen_factory = popen_factory
        self.poll_seconds = max(0.01, float(poll_seconds))
        self.wall_seconds = max(0.01, float(wall_seconds))
        self.idle_seconds = max(1.0, float(idle_seconds))
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.monotonic = monotonic
        self.last_child_finished: float | None = None
        self.last_deferred_window: str | None = None
        self.cancel = threading.Event()
        self.child: subprocess.Popen | None = None
        self.thread = threading.Thread(target=self._run, name="v35-zsxq-pdf-queue-drain", daemon=True)

    @classmethod
    def from_environment(
        cls,
        *,
        cycle_active: threading.Event | None = None,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        poll_seconds: float = 0.25,
        wall_seconds: float = PDF_QUEUE_CHILD_WALL_SECONDS,
        idle_seconds: float = 60.0,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        start: bool = True,
    ) -> "PdfQueueDrainHook | None":
        environment = dict(os.environ)
        data_root_text = environment.get("V35_DATA_ROOT", "").strip()
        if not data_root_text:
            return None
        data_root = Path(data_root_text)
        app_root = Path(environment.get("V35_APP_ROOT") or Path(__file__).resolve().parents[1])
        python_path = Path(sys.executable)
        if (
            not data_root.is_absolute()
            or ".." in data_root.parts
            or os.path.normpath(str(data_root)) != str(data_root)
            or not data_root.is_dir()
            or data_root.is_symlink()
        ):
            raise DaemonConfigurationError("PDF queue data root is invalid")
        if (
            not app_root.is_absolute()
            or ".." in app_root.parts
            or os.path.normpath(str(app_root)) != str(app_root)
            or not app_root.is_dir()
            or app_root.is_symlink()
            or not (app_root / "ops/run_zsxq_hourly_delta.py").is_file()
        ):
            raise DaemonConfigurationError("PDF queue app root is invalid")
        if not python_path.is_absolute() or not python_path.is_file() or not os.access(python_path, os.X_OK):
            raise DaemonConfigurationError("PDF queue interpreter is invalid")
        hook = cls(
            app_root=app_root,
            data_root=data_root,
            python_path=python_path,
            cycle_active=cycle_active,
            popen_factory=popen_factory,
            poll_seconds=poll_seconds,
            wall_seconds=wall_seconds,
            idle_seconds=idle_seconds,
            clock=clock,
            monotonic=monotonic,
        )
        if start:
            hook.thread.start()
        return hook

    def _queue_probe(self) -> dict[str, Any]:
        """Read only the owned index; the child remains the source validator.

        This deliberately does not verify PDF/source bytes or acquire model/data
        locks. An ambiguous index requests the existing low-frequency fallback.
        """
        from infrastructure.data_store import NativeDataStore
        from infrastructure.zsxq_pdf_ingestion import (
            _read_index, _latest_engine_run, _engine_run_is_retryable,
            _retry_backoff_remaining, PDF_QUEUE_RETRY_BACKOFF_SECONDS,
        )
        try:
            index = _read_index(NativeDataStore(self.data_root))
            waits = []
            for row in index["documents"].values():
                if not isinstance(row, Mapping):
                    raise ValueError("PDF_INDEX_DOCUMENT_INVALID")
                latest = _latest_engine_run(row)
                if latest is None:
                    return {"status": "PDF_QUEUE_INPUT_PENDING"}
                artifact = latest[1]
                if not _engine_run_is_retryable(artifact):
                    continue
                remaining = _retry_backoff_remaining(
                    artifact, now=self.clock(), backoff_seconds=PDF_QUEUE_RETRY_BACKOFF_SECONDS,
                )
                if not remaining:
                    return {"status": "PDF_QUEUE_INPUT_PENDING"}
                waits.append(remaining)
            if waits:
                return {"status": "RETRY_BACKOFF", "next_retry_seconds": min(waits)}
            return {"status": "NO_RETRYABLE_TASKS"}
        except Exception as error:
            return {"status": "CANNOT_CONFIRM", "reason_code": type(error).__name__}

    def _night_admission(self) -> dict[str, Any]:
        from infrastructure.zsxq_pdf_ingestion import pdf_queue_night_admission
        return pdf_queue_night_admission(self.clock())

    def _child_due(self) -> tuple[bool, float]:
        admission = self._night_admission()
        if not admission["allowed"]:
            key = str(admission.get("next_window_at") or admission["reason_code"])
            if key != self.last_deferred_window:
                _emit_pdf_queue({"schema_version": DAEMON_SCHEMA, "status": "PDF_QUEUE_DEFERRED",
                                 "admission": admission, "processed_document_count": 0,
                                 "ocr_invoked": False, "queue_mutated": False})
                self.last_deferred_window = key
            return False, min(self.idle_seconds, float(admission["wait_seconds"]))
        self.last_deferred_window = None
        probe = self._queue_probe()
        elapsed = (self.monotonic() - self.last_child_finished
                   if self.last_child_finished is not None else PDF_QUEUE_EMPTY_FALLBACK_SECONDS)
        fallback_remaining = max(0.0, PDF_QUEUE_EMPTY_FALLBACK_SECONDS - elapsed)
        if probe["status"] == "PDF_QUEUE_INPUT_PENDING" or fallback_remaining <= 0:
            return True, 0.0
        wait_seconds = min(self.idle_seconds, fallback_remaining)
        if probe["status"] == "RETRY_BACKOFF":
            wait_seconds = min(wait_seconds, max(1.0, float(probe["next_retry_seconds"])))
        return False, wait_seconds

    def _finish_child(self, child: subprocess.Popen, reason: str) -> None:
        try:
            if child.poll() is not None:
                child.wait(timeout=0)
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass
        try:
            child.wait(timeout=PDF_QUEUE_CHILD_KILL_GRACE_SECONDS)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            pass
        try:
            child.wait(timeout=PDF_QUEUE_CHILD_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            _emit_pdf_queue({"status": "PDF_QUEUE_CHILD_REAP_UNCONFIRMED", "reason": reason})

    def _run_child(self) -> dict[str, Any]:
        admission = self._night_admission()
        if not admission["allowed"]:
            from infrastructure.zsxq_pdf_ingestion import _pdf_queue_deferred
            return _pdf_queue_deferred(admission)
        command = [
            str(self.python_path),
            "-B",
            "-m",
            "ops.run_zsxq_hourly_delta",
            "--data-root",
            str(self.data_root),
            "--pdf-queue-tick",
            "--pdf-time-budget-seconds",
            str(PDF_QUEUE_TICK_SECONDS),
        ]
        environment = dict(os.environ)
        environment.update(
            PRODUCTION_ALLOWED="false",
            BUY_GATE_UPDATED="false",
            ORDERS_SENT="false",
            PYTHONNOUSERSITE="1",
        )
        if self.child is not None:
            return {"status": "PDF_QUEUE_CHILD_REAP_UNCONFIRMED"}
        child = None
        reaped = False
        try:
            with tempfile.TemporaryFile(mode="w+b") as stdout_file:
                child = self.popen_factory(
                    command,
                    cwd=str(self.app_root),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
                self.child = child
                deadline = time.monotonic() + self.wall_seconds
                while True:
                    try:
                        return_code = child.poll()
                    except Exception:
                        # A monitor failure is not evidence that the owner exited.
                        return_code = None
                    if return_code is not None:
                        try:
                            child.wait(timeout=0)
                            reaped = True
                        except (OSError, subprocess.TimeoutExpired):
                            return {"status": "PDF_QUEUE_CHILD_REAP_UNCONFIRMED"}
                        stdout_file.seek(0)
                        raw = stdout_file.read(65537)
                        if len(raw) > 65536:
                            return {"status": "PDF_QUEUE_OUTPUT_OVERSIZED"}
                        payload = _parse_scheduler_output(raw.decode("utf-8", errors="replace"))
                        if payload is None:
                            return {"status": "PDF_QUEUE_OUTPUT_MISSING", "return_code": return_code}
                        payload = _pdf_queue_safe_summary(payload)
                        if return_code != 0 and payload.get("status") not in {"CANNOT_CONFIRM", "RETRY_BACKOFF"}:
                            payload["runner_status"] = "FAILED"
                        return payload
                    if self.cancel.is_set():
                        self._finish_child(child, "CANCELLED")
                        reaped = child.returncode is not None
                        return {"status": "PDF_QUEUE_CHILD_CANCELLED"}
                    if time.monotonic() >= deadline:
                        self._finish_child(child, "TIMEOUT")
                        reaped = child.returncode is not None
                        return {"status": "PDF_QUEUE_CHILD_TIMEOUT"}
                    self.cancel.wait(self.poll_seconds)
        except Exception as error:
            return {"status": "PDF_QUEUE_CHILD_START_FAILED", "error_code": type(error).__name__}
        finally:
            if child is None or reaped:
                self.child = None
                self.last_child_finished = self.monotonic()

    def _run(self) -> None:
        while not self.cancel.is_set():
            if self.cycle_active.is_set():
                self.cancel.wait(self.poll_seconds)
                continue
            due, wait_seconds = self._child_due()
            if not due:
                self.cancel.wait(wait_seconds)
                continue
            result = self._run_child()
            summary = _pdf_queue_safe_summary(result)
            try:
                _emit_pdf_queue({"status": "PDF_QUEUE_TICK", **summary})
            except Exception:
                # Logging does not release a process owner or duplicate work.
                pass
            if self.cancel.is_set():
                break
            if self.child is not None:
                self.cancel.wait(self.idle_seconds)
            elif summary.get("status") == "NO_RETRYABLE_TASKS":
                self.cancel.wait(self.idle_seconds)
            elif summary.get("status") == "RETRY_BACKOFF":
                wait_seconds = summary.get("next_retry_seconds")
                self.cancel.wait(min(self.idle_seconds, max(1.0, float(wait_seconds or self.idle_seconds))))
            elif summary.get("status") in {"PDF_QUEUE_CHILD_TIMEOUT", "PDF_QUEUE_OUTPUT_MISSING", "PDF_QUEUE_OUTPUT_OVERSIZED", "PDF_QUEUE_CHILD_START_FAILED"}:
                self.cancel.wait(min(self.idle_seconds, 30.0))
            else:
                self.cancel.wait(1.0)

    def stop(self, *, join_seconds: float = 3.0) -> None:
        self.cancel.set()
        child = self.child
        if child is not None:
            self._finish_child(child, "CANCELLED")
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=max(0.0, join_seconds))
            if self.thread.is_alive():
                _emit_pdf_queue({"status": "PDF_QUEUE_HOOK_JOIN_TIMEOUT"})

class SlotProcessLanes:
    """Bounded execution adapter around the original one-shot scheduler.

    The full 1700 slot owns A_LONG; every other fixed slot keeps one serial
    DEFAULT lane. Claims are created by the original child dispatcher and use
    that child's PID. Observations never reserve or release business claims.
    """
    def __init__(self, scheduler_argv, *, release_id, popen_factory=subprocess.Popen, clock=None):
        from infrastructure.scheduling.execution_ledger import ExecutionLedger
        self.argv = list(scheduler_argv)
        ledger = _option_value(self.argv, "--ledger-root")
        if not ledger or not Path(ledger).is_absolute():
            raise DaemonConfigurationError("lane adapter requires an absolute ledger root")
        if _option_value(self.argv, "--slot") or _option_value(self.argv, "--date"):
            raise DaemonConfigurationError("daemon lanes require natural slot resolution")
        self.ledger = ExecutionLedger(Path(ledger))
        self.release_id = release_id
        self.popen_factory = popen_factory
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.active: dict[str, dict[str, Any]] = {}
        self.queued: dict[tuple[str, str], dict[str, Any]] = {}
        self.app_root = Path(__file__).resolve().parents[1]

    @staticmethod
    def lane(slot):
        return "A_LONG" if slot == "1700" else "DEFAULT"

    @staticmethod
    def _log(payload):
        try: _emit(payload)
        except Exception: pass  # a log sink cannot revoke a child owner

    def _observe(self, job, state, moment, **extra):
        payload = {"status": state, "lane": self.lane(job["slot"]),
            "planned_at": job["planned_at"], "queued_at": job["queued_at"],
            "observed_at": moment.isoformat(), "cutoff_at": job["cutoff_at"], **extra}
        try:
            self.ledger.write_scheduler_observation(job["business_date"], job["slot"], payload)
        except Exception as error:
            self._log({"status": "SCHEDULER_OBSERVATION_CANNOT_CONFIRM", "state": state,
                       "slot": job["slot"], "pid": extra.get("pid"), "error_code": type(error).__name__})
        return payload

    def enqueue_due(self, moment):
        day = moment.strftime("%Y%m%d")
        excluded = frozenset(slot for date, slot in self.queued if date == day) | frozenset(
            job["slot"] for job in self.active.values() if job["business_date"] == day)
        due = scheduler.resolve_due_slot(ledger_root=self.ledger.root, now=moment,
            release_id=self.release_id,
            upstream_fingerprint=_option_value(self.argv, "--upstream-fingerprint") or None,
            excluded_slots=excluded)
        slot = due.get("slot")
        if slot not in scheduler.ALL_SLOTS:
            return due
        self.enqueue(due["business_date"], slot, moment)
        return due

    def enqueue(self, business_date, slot, moment):
        if slot not in scheduler.ALL_SLOTS:
            raise ValueError("UNKNOWN_SLOT")
        key = (business_date, slot)
        if key in self.queued or any((j["business_date"], j["slot"]) == key for j in self.active.values()):
            return
        planned = datetime.strptime(business_date + slot, "%Y%m%d%H%M").replace(tzinfo=SHANGHAI)
        cutoff = scheduler._slot_retry_deadline(business_date, slot)
        job = {"business_date": business_date, "slot": slot, "planned_at": planned.isoformat(),
               "queued_at": moment.isoformat(), "cutoff_at": cutoff.isoformat()}
        if moment > cutoff:
            self._observe(job, "EXPIRED", moment, reason="ORIGINAL_SLOT_CUTOFF_PASSED")
            return
        self.queued[key] = job
        blocker = self.active.get(self.lane(slot))
        self._observe(job, "QUEUED_BEHIND" if blocker else "QUEUED", moment,
            blocking_slot=blocker["slot"] if blocker else None,
            blocking_pid=blocker["child"].pid if blocker else None)

    def pulse(self, moment, *, dispatch=True):
        for lane, job in list(self.active.items()):
            child = job["child"]
            try:
                code = child.poll()
                if code is None: continue
                child.wait(timeout=0)
            except Exception as error:
                if job.get("monitor_error") != type(error).__name__:
                    job["monitor_error"] = type(error).__name__
                    self._observe(job, "RUNNING_CANNOT_CONFIRM", moment, pid=child.pid,
                                  error_code=type(error).__name__)
                continue
            # Only a confirmed wait/reap permits dropping this owner handle.
            result = None
            try:
                job["stdout"].seek(0)
                raw = job["stdout"].read(65537)
                if len(raw) <= 65536:
                    result = _parse_scheduler_output(raw.decode("utf-8", errors="replace"))
                if result is not None: _validate_scheduler_result(result, self.release_id)
            except Exception:
                result = None
            self._observe(job, "FINISHED" if result is not None else "FINISHED_CANNOT_CONFIRM", moment,
                pid=child.pid, actual_started_at=job["started_at"], return_code=code,
                result_status=result.get("status") if result else None)
            for stream in (job["stdout"], job["stderr"]):
                try: stream.close()
                except Exception: pass
            del self.active[lane]
        for key, job in list(self.queued.items()):
            moment = _as_shanghai(self.clock())
            cutoff = datetime.fromisoformat(job["cutoff_at"])
            if moment > cutoff:
                self._observe(job, "EXPIRED", moment, reason="QUEUED_PAST_ORIGINAL_CUTOFF")
                del self.queued[key]
                continue
            lane = self.lane(job["slot"])
            if not dispatch or lane in self.active: continue
            if moment < datetime.fromisoformat(job.get("next_start_at", job["queued_at"])): continue
            lane_fd = self.ledger.try_acquire_scheduler_lane(lane)
            if lane_fd is None:
                if not job.get("waiting_for_inherited_lane"):
                    self._observe(job, "QUEUED_BEHIND", moment, blocking_slot=None,
                                  blocking_pid=None, reason="PERSISTED_LANE_OWNER_ACTIVE")
                    job["waiting_for_inherited_lane"] = True
                continue
            out = err = None
            child = None
            try:
                # Claims and pointer I/O can take time. The plan moment is not
                # permission to start after the original cutoff.
                if scheduler._slot_blocks_retry(self.ledger.root, job["business_date"], job["slot"], moment=moment):
                    self._observe(job, "CLAIM_OR_RECEIPT_BLOCKED", _as_shanghai(self.clock()))
                    del self.queued[key]
                    continue
                out = tempfile.TemporaryFile(mode="w+b")
                err = tempfile.TemporaryFile(mode="w+b")
                command = [sys.executable, "-B", "-m", "ops.run_v35_macos_scheduler", *self.argv,
                           "--slot", job["slot"], "--date", job["business_date"]]
                environment = dict(os.environ)
                environment.update(PRODUCTION_ALLOWED="false", BUY_GATE_UPDATED="false", ORDERS_SENT="false",
                    PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
                    V35_SCHEDULER_LANE_FD=str(lane_fd), V35_SCHEDULER_LANE_NAME=lane,
                    V35_SCHEDULER_RESOLVED_DATE=job["business_date"], V35_SCHEDULER_RESOLVED_SLOT=job["slot"])
                started_at = _as_shanghai(self.clock())
                if started_at.strftime("%Y%m%d") != job["business_date"] or started_at > cutoff:
                    self._observe(job, "EXPIRED", started_at, reason="QUEUED_PAST_ORIGINAL_CUTOFF")
                    del self.queued[key]
                    continue
                child = self.popen_factory(command, cwd=str(self.app_root), env=environment,
                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                    close_fds=True, pass_fds=(lane_fd,))
                # Install ownership before any observation/log I/O can fail.
                self.active[lane] = {**job, "child": child, "stdout": out, "stderr": err,
                                     "started_at": started_at.isoformat()}
                del self.queued[key]
                self._observe(job, "RUNNING", started_at, pid=child.pid, actual_started_at=started_at.isoformat())
            except Exception as error:
                if child is not None:
                    self.active[lane] = {**job, "child": child, "stdout": out, "stderr": err,
                                         "started_at": started_at.isoformat()}
                    self.queued.pop(key, None)
                    continue
                job["next_start_at"] = (_as_shanghai(self.clock()) + timedelta(seconds=300)).isoformat()
                self._observe(job, "CHILD_START_FAILED", _as_shanghai(self.clock()), error_code=type(error).__name__)
            finally:
                # close(), never LOCK_UN: the child's inherited description
                # still owns this lane even if this parent immediately dies.
                os.close(lane_fd)
                if child is None:
                    for stream in (out, err):
                        if stream is not None:
                            try: stream.close()
                            except Exception: pass

    def wait_for_children(self, clock):
        # Graceful daemon stop does not cancel a healthy child or release its
        # claims. SIGKILL of the parent also leaves child-PID claims alive.
        if self.active:
            self._log({"status": "DAEMON_WAITING_FOR_CHILDREN",
                       "pids": [job["child"].pid for job in self.active.values()]})
        while self.active:
            self.pulse(_as_shanghai(clock()), dispatch=False)
            if self.active: time.sleep(0.05)


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

    announcement_hook: AnnouncementCycleHook | None = None
    try:
        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", "").strip():
            # Fail closed: never initialize the old capture owner on this branch.
            from v4.manager_workbench.supervisor import WorkbenchHook
            announcement_hook = WorkbenchHook.from_environment(clock=now)
        else:
            announcement_hook = AnnouncementCycleHook.from_environment(clock=now)
    except DaemonConfigurationError as error:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "ANNOUNCEMENT_HOOK_DISABLED",
                "error": _bounded_error(error),
                "release_id": release_id,
            }
        )
    except Exception as error:
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "ANNOUNCEMENT_HOOK_DISABLED",
                "error": _bounded_error(error),
                "release_id": release_id,
            }
        )
    scheduler_cycle_active = threading.Event()
    scheduler_cycle_active.set()
    pdf_queue_hook: PdfQueueDrainHook | None = None
    pdf_queue_drain_state: dict[str, Any] = {"status": "DISABLED", "reason": "V35_DATA_ROOT_NOT_CONFIGURED"}
    try:
        pdf_queue_hook = PdfQueueDrainHook.from_environment(cycle_active=scheduler_cycle_active)
        if pdf_queue_hook is not None:
            pdf_queue_drain_state = {"status": "ACTIVE", "execution_owner": "DAEMON_BACKGROUND_THREAD", "queue_source": "OWNED_PDF_INGESTION_INDEX", "latest_tick_status": "NOT_OBSERVED"}
        elif os.environ.get("V35_DATA_ROOT", "").strip():
            pdf_queue_drain_state = {"status": "DISABLED", "reason": "PDF_QUEUE_CONFIGURATION_UNAVAILABLE"}
    except Exception as error:
        reason = _bounded_error(error)
        pdf_queue_hook = None
        pdf_queue_drain_state = {"status": "DISABLED", "reason": reason}
        _emit_pdf_queue({"schema_version": DAEMON_SCHEMA, "status": "PDF_QUEUE_HOOK_DISABLED", "release_id": release_id, "error": reason})
    process_lanes = None
    if scheduler_main is scheduler.main:
        try:
            process_lanes = SlotProcessLanes(scheduler_argv, release_id=release_id, clock=now)
        except DaemonConfigurationError as error:
            if pdf_queue_hook is not None: pdf_queue_hook.stop()
            if announcement_hook is not None: announcement_hook.stop()
            if previous_handlers: _restore_signal_handlers(previous_handlers)
            _emit({"status": "DAEMON_FATAL", "error": _bounded_error(error)})
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
                "pdf_queue_drain": pdf_queue_drain_state,
            }
        )
        while not event.is_set():
            moment = _as_shanghai(now())
            minute = _minute_key(moment)
            if process_lanes is not None:
                process_lanes.pulse(moment)
                if process_lanes.active: scheduler_cycle_active.set()
                else: scheduler_cycle_active.clear()
            if minute != last_minute:
                last_minute = minute
                cycles += 1
                scheduler_cycle_active.set()
                try:
                    if process_lanes is not None:
                        due = process_lanes.enqueue_due(moment)
                        process_lanes.pulse(moment)
                        SlotProcessLanes._log({"schema_version": DAEMON_SCHEMA, "status": "DAEMON_DISPATCH_CYCLE",
                            "minute": minute, "slot": due.get("slot"), "active_children": len(process_lanes.active),
                            "queued_slots": len(process_lanes.queued), "production_allowed": False,
                            "buy_gate_updated": False, "orders_sent": False})
                    else:
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
                finally:
                    if process_lanes is not None and process_lanes.active:
                        scheduler_cycle_active.set()
                    else:
                        scheduler_cycle_active.clear()
            wait_for = min(
                float(poll_interval_seconds), _seconds_to_next_minute(moment)
            )
            event.wait(max(0.001, wait_for))
        if process_lanes is not None:
            process_lanes.wait_for_children(now)
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
        if process_lanes is not None:
            process_lanes.wait_for_children(now)
        if pdf_queue_hook is not None:
            pdf_queue_hook.stop()
        if announcement_hook is not None:
            announcement_hook.stop()
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
    "AnnouncementCycleHook",
    "PdfQueueDrainHook",
    "DaemonConfigurationError",
    "last_emitted_output",
    "main",
    "run_daemon",
]
