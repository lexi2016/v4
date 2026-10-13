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
import importlib.util
import io
import json
import os
import signal
import stat
import subprocess
import sys
import threading
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


def _release_inventory_entries(root: Path) -> list[dict[str, Any]]:
    """Recompute the release builder's closed app inventory for a pinned root."""
    entries: list[dict[str, Any]] = []
    for directory, child_dirs, filenames in os.walk(root, followlinks=False):
        child_dirs.sort()
        filenames.sort()
        base = Path(directory)
        ordinary_dirs: list[str] = []
        for name in child_dirs:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path),
                                "target_exists": path.exists()})
            else:
                ordinary_dirs.append(name)
        child_dirs[:] = ordinary_dirs
        for name in filenames:
            path = base / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path),
                                "target_exists": path.exists()})
            elif stat.S_ISREG(info.st_mode):
                entries.append({"path": relative, "kind": "file", "sha256": _sha256_file(path),
                                "mode": f"{stat.S_IMODE(info.st_mode):04o}", "size": info.st_size})
            else:
                raise DaemonConfigurationError("plan canary app contains an unsupported file type")
    return sorted(entries, key=lambda item: item["path"])


def _json_identity_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_candidate_app_plan_binding(binding: Mapping[str, Any], app_root: Path) -> None:
    """Run the original API-root binding validator against the exact pinned app."""
    supervisor_path = app_root / "infrastructure/scheduling/manager_announcement_supervisor.py"
    cycle_path = app_root / "ops/run_manager_announcement_cycle.py"
    owned_io_path = app_root / "infrastructure/owned_io.py"
    calendar_path = app_root / "contracts/trading_calendar.py"
    if any(not path.is_file() or path.resolve(strict=True) != path
           for path in (supervisor_path, cycle_path, owned_io_path, calendar_path)):
        raise DaemonConfigurationError("plan canary candidate validator sources are unavailable")

    # The scheduler process may already have imported its own `ops` and
    # `contracts` packages. Temporarily pin the API root's cycle, SafeRoot,
    # and historical-session calendar modules while invoking the API app's
    # original validator, then restore all import state.
    names = (
        "ops.run_manager_announcement_cycle",
        "infrastructure.owned_io",
        "contracts.trading_calendar",
    )
    missing = object()
    saved_modules = {name: sys.modules.get(name, missing) for name in names}
    parent_attrs: dict[tuple[str, str], Any] = {}
    original_path = list(sys.path)
    sys.path.insert(0, str(app_root))
    try:
        for qualified, path in (
            (names[0], cycle_path),
            (names[1], owned_io_path),
            (names[2], calendar_path),
        ):
            spec = importlib.util.spec_from_file_location(qualified, path)
            if spec is None or spec.loader is None:
                raise DaemonConfigurationError("plan canary candidate validator source is unreadable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[qualified] = module
            parent_name, attribute = qualified.rsplit(".", 1)
            parent = sys.modules.get(parent_name)
            if parent is None:
                parent = importlib.import_module(parent_name)
            parent_attrs[(parent_name, attribute)] = getattr(parent, attribute, missing)
            setattr(parent, attribute, module)
            spec.loader.exec_module(module)

        spec = importlib.util.spec_from_file_location(
            "_v4_candidate_manager_announcement_supervisor", supervisor_path)
        if spec is None or spec.loader is None:
            raise DaemonConfigurationError("plan canary candidate validator source is unreadable")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.validate_binding(dict(binding), expected_app=app_root)
    except DaemonConfigurationError:
        raise
    except Exception as error:
        raise DaemonConfigurationError("plan canary owner evidence failed API supervisor validation") from error
    finally:
        sys.path[:] = original_path
        for name, value in saved_modules.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
        for (parent_name, attribute), value in parent_attrs.items():
            parent = sys.modules.get(parent_name)
            if parent is None:
                continue
            if value is missing:
                try:
                    delattr(parent, attribute)
                except AttributeError:
                    pass
            else:
                setattr(parent, attribute, value)


def _validate_same_root_plan_canary_inventory(
    canary: Mapping[str, Any], binding: Mapping[str, Any], app_root: Path,
) -> None:
    """Require a same-root canary to pin this release and both source inventories."""
    manifest_path = app_root.parent / "release-manifest.json"
    try:
        if (manifest_path.is_symlink() or not manifest_path.is_file()
                or manifest_path.resolve(strict=True) != manifest_path):
            raise ValueError("manifest path is not an exact regular file")
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes)
        candidate = manifest.get("candidate") if isinstance(manifest, dict) else None
        stored_inventory = manifest.get("application_inventory") if isinstance(manifest, dict) else None
        entries = stored_inventory.get("entries") if isinstance(stored_inventory, dict) else None
        if (not isinstance(candidate, dict) or not isinstance(stored_inventory, dict)
                or not isinstance(entries, list) or stored_inventory.get("entry_count") != len(entries)
                or candidate.get("app_root") != str(app_root)
                or manifest.get("schema_version") != "v4.release_candidate.v1"):
            raise ValueError("manifest identity is invalid")
        actual_entries = _release_inventory_entries(app_root)
        inventory_sha = _json_identity_sha(entries)
        if (entries != actual_entries or inventory_sha != stored_inventory.get("aggregate_sha256")
                or inventory_sha != _json_identity_sha(actual_entries)):
            raise ValueError("manifest inventory does not match app bytes")
        binding_files = binding.get("files")
        if not isinstance(binding_files, dict):
            raise ValueError("binding source inventory is missing")
        source_inventory_sha = _json_identity_sha(binding_files)
        expected = {
            "candidate_release_id": candidate.get("release_id"),
            "candidate_release_manifest_path": str(manifest_path),
            "candidate_release_manifest_sha256": manifest_sha,
            "candidate_application_inventory_sha256": inventory_sha,
            "candidate_manager_source_inventory_sha256": source_inventory_sha,
        }
        if any(canary.get(field) != value for field, value in expected.items()):
            raise ValueError("canary release or source inventory pin is stale")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise DaemonConfigurationError("same-root plan canary release or source inventory pin is invalid") from error


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
        owner_app_root=_exact_path(canary.get("owner_execution_app_root"))
        if owner_app_root==app_root:
            _validate_same_root_plan_canary_inventory(canary,binding,app_root)
        # The API root owns the authoritative closed inventory and manual
        # refresh/readback validator. Cross-root evidence remains subject to
        # its exact owner-source migration proof; same-root evidence receives
        # that same full validation after its release and inventory pins pass.
        _validate_candidate_app_plan_binding(binding,app_root)
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
        "announcement_collection_enabled": collection,
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
    announcement_cycle_state = {
        "status": "DISABLED",
        "reason": "ANNOUNCEMENT_BINDING_NOT_CONFIGURED",
    }
    announcement_collection_state = {
        "status": "UNAVAILABLE",
        "reason": "ANNOUNCEMENT_BINDING_NOT_CONFIGURED",
    }
    plan_material_refresh_only: bool | None = None
    try:
        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", "").strip():
            # Fail closed: never initialize the old capture owner on this branch.
            from v4.manager_workbench.supervisor import WorkbenchHook
            announcement_hook = WorkbenchHook.from_environment(clock=now)
        else:
            announcement_hook = AnnouncementCycleHook.from_environment(clock=now)
        if announcement_hook is None:
            reason = ("ANNOUNCEMENT_BINDING_DISABLED"
                      if os.environ.get(ANNOUNCEMENT_BINDING_ENV, "").strip()
                      else "ANNOUNCEMENT_BINDING_NOT_CONFIGURED")
            announcement_cycle_state = {"status": "DISABLED", "reason": reason}
            announcement_collection_state = {"status": "UNAVAILABLE", "reason": reason}
        else:
            identity = announcement_hook.identity
            plan_material_refresh_only = identity["plan_material_refresh_only"]
            announcement_cycle_state = {"status": "ACTIVE", "reason": None}
            collection_enabled = identity["announcement_collection_enabled"]
            if collection_enabled:
                announcement_collection_state = {"status": "ENABLED", "reason": None}
            elif plan_material_refresh_only:
                announcement_collection_state = {
                    "status": "DISABLED_PLAN_REFRESH_ONLY",
                    "reason": "PLAN_MATERIAL_REFRESH_ONLY",
                }
            else:
                announcement_collection_state = {
                    "status": "DISABLED",
                    "reason": "ANNOUNCEMENT_COLLECTION_DISABLED",
                }
    except DaemonConfigurationError as error:
        reason = _bounded_error(error)
        announcement_cycle_state = {"status": "DISABLED", "reason": reason}
        announcement_collection_state = {"status": "UNAVAILABLE", "reason": reason}
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "ANNOUNCEMENT_HOOK_DISABLED",
                "error": reason,
                "release_id": release_id,
            }
        )
    except Exception as error:
        reason = _bounded_error(error)
        announcement_cycle_state = {"status": "DISABLED", "reason": reason}
        announcement_collection_state = {"status": "UNAVAILABLE", "reason": reason}
        _emit(
            {
                "schema_version": DAEMON_SCHEMA,
                "status": "ANNOUNCEMENT_HOOK_DISABLED",
                "error": reason,
                "release_id": release_id,
            }
        )
    # Readiness reports distinguish static ownership/configuration from the
    # latest semantic run. This daemon has no heartbeat receipt reader, so it
    # must not infer a success or gap from hook configuration.
    announcement_collection_state = {
        **announcement_collection_state,
        "execution_owner": "HEARTBEAT",
        "ownership_status": "HEARTBEAT_OWNED",
        "scheduler_hook_enabled": bool(
            announcement_hook is not None
            and announcement_hook.identity.get("announcement_collection_enabled") is True
        ),
        "configuration_status": announcement_collection_state.get("status"),
        "configuration_reason": announcement_collection_state.get("reason"),
        "latest_execution_status": "NOT_RUN",
        "latest_success_status": "CANNOT_CONFIRM",
        "latest_gap_status": "CANNOT_CONFIRM",
        "latest_receipt_status": "NOT_OBSERVED",
    }
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
                "critical_task_states": {
                    "announcement_cycle_hook": announcement_cycle_state,
                    "announcement_collection": announcement_collection_state,
                    "plan_material_refresh_only": plan_material_refresh_only,
                },
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
    "DaemonConfigurationError",
    "last_emitted_output",
    "main",
    "run_daemon",
]
