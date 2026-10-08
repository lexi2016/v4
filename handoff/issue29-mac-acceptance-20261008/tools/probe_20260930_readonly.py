#!/usr/bin/env python3
"""One-shot, in-process, read-only historical Manager GET probe for the Reviewer.

This script never starts uvicorn or contacts the live listener. It reconstructs
the allowlisted runtime configuration from the active LaunchAgent, imports the
isolated candidate API, and calls only the existing historical GET route via
ASGI. Filesystem writes are blocked before candidate application code is
imported or constructed.
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import sys
from typing import Any


EXPECTED_LABEL = "com.lexi.v35.api-only"
EXPECTED_PLIST_SHA256 = "495a9be82e715979d59c03f5c4dd883a7570c55f15b72fa5ed309cacb3914356"
EXPECTED_PID = 34989
TARGET_DATE = "20260930"
TARGET_RUN_ID = "ba13fba330464300b760fe940ba579a1"
TARGET_PATH = "/api/v4/manager/research/workspace?date=20260930&view=historical"
MAX_PLAN_BYTES = 320 * 1024 * 1024

SAFE_ENV_NAMES = frozenset({
    "V35_APP_ROOT", "V35_DATA_ROOT", "V35_MORNING_NEWS_DATA_ROOT",
    "V35_PRESELECTION_SOURCE_ROOT", "V35_RELEASE_ID",
    "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256",
    "V35_RESEARCH_DATA_ROOT", "V35_REVIEW_CORE_CLOSE_ROOT",
    "V35_REVIEW_CORE_FUPAN_STORE_ROOT", "V35_REVIEW_CORE_PACKAGE_ROOT",
    "V35_REVIEW_CORE_RUNTIME_ROOT", "V35_REVIEW_CORE_STAGE7_STORE_ROOT",
    "V35_RUNTIME_ROOT", "V35_SHARED_DATA_ROOT",
    "V35_STAGE_CENTER_SELECTION_ROOT", "V35_STAGE_MODE", "V35_DISPATCH_LEDGER_ROOT",
    "V4_CLOSE_REBOUND_AUTHORITY_ROOT", "V4_DAILY_REVIEW_ROOT",
    "V4_INTRADAY_RESEARCH_ROOT", "V4_MANAGER_NEWS_DATA_ROOT",
    "V4_MANAGER_NEWS_OWNER_ROOT", "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
    "V4_MANAGER_RESEARCH_STATE_ROOT", "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
    "V4_MANAGER_SECURITY_MASTER_ROOT", "V4_MANAGER_UNIVERSE_OWNER_ROOT",
    "V4_MANAGER_UNIVERSE_OWNER_SHA256", "V4_MANAGER_UNIVERSE_ROOT",
    "V4_MANAGER_VIBE_BINDING",
    "V4_REVIEW_GENERATION_BINDINGS_PATH",
    "V4_REVIEW_GENERATION_BINDINGS_SHA256", "V4_WECHAT_ARCHIVE_ROOT",
    "REVIEW_CORE_DATA_ROOT", "REVIEW_CORE_FUPAN_POOL_ROOT",
    "REVIEW_CORE_PACKAGE_ROOT", "REVIEW_CORE_STAGE7_POOL_ROOT",
    "RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT",
})
SAFE_INHERITED_ENV = frozenset({"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"})
SAFE_ATTEMPT_FIELDS = (
    "attempt_id", "run_id", "execution_kind", "status", "started_at",
    "finished_at", "original_owner", "sha256", "plan_sha256",
)


class ProbeAbort(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReadOnlyWriteBlocked(ProbeAbort):
    def __init__(self):
        super().__init__("READ_ONLY_WRITE_BLOCKED")


def emit(**values: Any) -> None:
    print(json.dumps(values, sort_keys=True, separators=(",", ":")))


def read_launch_configuration(plist_path: Path, expected_pid: int) -> tuple[dict[str, str], argparse.Namespace]:
    try:
        raw = plist_path.read_bytes()
    except OSError as exc:
        raise ProbeAbort("ACTIVE_PLIST_UNREADABLE") from exc
    if hashlib.sha256(raw).hexdigest() != EXPECTED_PLIST_SHA256:
        raise ProbeAbort("ACTIVE_PLIST_SHA256_CHANGED")
    try:
        plist = plistlib.loads(raw)
    except Exception as exc:
        raise ProbeAbort("ACTIVE_PLIST_INVALID") from exc
    if plist.get("Label") != EXPECTED_LABEL:
        raise ProbeAbort("ACTIVE_PLIST_LABEL_MISMATCH")

    try:
        os.kill(expected_pid, 0)
    except OSError as exc:
        raise ProbeAbort("EXPECTED_ACTIVE_PID_NOT_RUNNING") from exc
    # launchctl output is consumed only in memory; it is never printed.
    try:
        import subprocess

        checked = subprocess.run(
            ["/bin/launchctl", "list", EXPECTED_LABEL],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        raise ProbeAbort("LAUNCH_AGENT_IDENTITY_UNAVAILABLE") from exc
    if checked.returncode != 0:
        raise ProbeAbort("LAUNCH_AGENT_IDENTITY_UNAVAILABLE")
    pid_value: int | None = None
    label_seen = False
    for line in checked.stdout.splitlines():
        plist_pid = re.search(r'(?m)^\s*"?PID"?\s*=\s*"?(\d+)"?\s*;', line)
        plist_label = re.search(r'(?m)^\s*"?Label"?\s*=\s*"([^"]+)"\s*;', line)
        row = re.match(r"^\s*(\d+|-)\s+-?\d+\s+([^\s]+)\s*$", line)
        if plist_pid:
            pid_value = int(plist_pid.group(1))
        elif row and row.group(2) == EXPECTED_LABEL and row.group(1).isdigit():
            pid_value = int(row.group(1))
        if plist_label and plist_label.group(1) == EXPECTED_LABEL:
            label_seen = True
        elif row and row.group(2) == EXPECTED_LABEL:
            label_seen = True
    if pid_value != expected_pid or not label_seen:
        raise ProbeAbort("LAUNCH_AGENT_PID_OR_LABEL_CHANGED")

    program_args = plist.get("ProgramArguments")
    if not isinstance(program_args, list) or not program_args:
        raise ProbeAbort("ACTIVE_LAUNCH_ARGUMENTS_MISSING")
    env_values: dict[str, str] = {}
    configured_env = plist.get("EnvironmentVariables")
    if isinstance(configured_env, dict):
        env_values.update({str(k): str(v) for k, v in configured_env.items()})
    index = 1 if Path(str(program_args[0])).name == "env" else 0
    assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
    while index < len(program_args):
        match = assignment.fullmatch(str(program_args[index]))
        if not match:
            break
        env_values[match.group(1)] = match.group(2)
        index += 1
    command = [str(item) for item in program_args[index:]]
    if not command or Path(command[0]).name != "python":
        raise ProbeAbort("ACTIVE_LAUNCH_COMMAND_UNSUPPORTED")
    # The active plist invokes Python as ``python -B -m apps.api.v35_api.run``.
    # Treat Python flags as an explicit allowlist and advance past them before
    # parsing the application arguments; never pass the module name to argparse.
    module_index = 1
    python_flags: list[str] = []
    while module_index < len(command) and command[module_index] != "-m":
        flag = command[module_index]
        if flag not in {"-B"}:
            raise ProbeAbort("ACTIVE_PYTHON_RUNTIME_FLAG_UNSUPPORTED")
        python_flags.append(flag)
        module_index += 1
    if python_flags != ["-B"] or command[module_index:module_index + 2] != ["-m", "apps.api.v35_api.run"]:
        raise ProbeAbort("ACTIVE_LAUNCH_COMMAND_UNSUPPORTED")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8873, type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--preselection-source-root", type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument("--stage-mode", choices=("shared", "local"), default=env_values.get("V35_STAGE_MODE", "shared"))
    try:
        launch = parser.parse_args(command[module_index + 2:])
    except SystemExit as exc:
        raise ProbeAbort("ACTIVE_LAUNCH_ARGUMENTS_UNSUPPORTED") from exc
    if launch.host not in {"127.0.0.1", "localhost", "::1"} or launch.port != 8873:
        raise ProbeAbort("ACTIVE_LISTENER_BINDING_CHANGED")
    if launch.stage_mode != "shared" or launch.stage_selection_root is None:
        raise ProbeAbort("ACTIVE_STAGE_MODE_NOT_SHARED")
    for key in ("RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        actual = env_values.get(key, env_values.get(key.lower(), "")).strip().lower()
        allowed = {"true", "1", "yes", "on"} if key == "RESEARCH_ONLY" else {"false", "0", "no", "off"}
        if actual not in allowed:
            raise ProbeAbort("ACTIVE_FINANCIAL_SAFETY_FLAGS_MISMATCH")

    inherited = {key: os.environ[key] for key in SAFE_INHERITED_ENV if key in os.environ}
    filtered = {key: value for key, value in env_values.items() if key in SAFE_ENV_NAMES}
    os.environ.clear()
    os.environ.update(inherited)
    os.environ.update(filtered)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["V35_STAGE_MODE"] = "shared"
    candidate_api = Path(__file__).resolve().parents[1] / "candidate" / "api"
    if not candidate_api.is_dir():
        raise ProbeAbort("CANDIDATE_API_ROOT_MISSING")
    os.environ["PYTHONPATH"] = str(candidate_api)
    sys.path.insert(0, str(candidate_api))
    return env_values, launch


def _block_write(*_args: Any, **_kwargs: Any) -> Any:
    raise ReadOnlyWriteBlocked()


def install_write_guards() -> None:
    # Guard normal Python and POSIX file-write paths used by this application.
    real_builtin_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open

    def read_only_file_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise ReadOnlyWriteBlocked()
        return real_builtin_open(file, mode, *args, **kwargs)

    def read_only_io_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise ReadOnlyWriteBlocked()
        return real_io_open(file, mode, *args, **kwargs)

    def read_only_os_open(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        forbidden = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & forbidden:
            raise ReadOnlyWriteBlocked()
        return real_os_open(path, flags, mode, dir_fd=dir_fd)

    builtins.open = read_only_file_open
    io.open = read_only_io_open
    os.open = read_only_os_open
    for name in (
        "mkdir", "makedirs", "unlink", "remove", "rmdir", "replace", "rename",
        "chmod", "chown", "utime", "truncate", "ftruncate", "link", "symlink",
        "write", "pwrite", "pwritev",
    ):
        if hasattr(os, name):
            setattr(os, name, _block_write)

    from infrastructure.owned_io import SafeRoot

    def check_only_directory(self: Any, relative: str | None = None) -> None:
        with self.directory(relative, create=False):
            pass

    SafeRoot.ensure_directory = check_only_directory
    SafeRoot.write_bytes = _block_write
    SafeRoot.unlink_if_same = _block_write

    @contextmanager
    def read_only_kernel_lock(self: Any, relative: str, *, timeout: float = 10.0, poll: float = 0.02):
        # A lock is allowed only on an already-existing file. Never create one.
        if not (timeout >= 0 and poll > 0):
            raise ProbeAbort("LOCK_ARGUMENTS_INVALID")
        import fcntl
        with self.parent(relative) as (parent, name):
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                import stat

                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ProbeAbort("EXISTING_LOCK_NOT_REGULAR")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ProbeAbort("EXISTING_LOCK_BUSY") from exc
                try:
                    yield fd
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    SafeRoot.kernel_lock = read_only_kernel_lock


def _existing_regular(root: Path, relative: str) -> os.stat_result:
    from infrastructure.owned_io import SafeRoot

    io_root = SafeRoot(root)
    with io_root.parent(relative) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            import stat

            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProbeAbort("TARGET_INPUT_NOT_REGULAR")
            return info
        finally:
            os.close(fd)


async def _get_once(app: Any) -> tuple[int, dict[str, Any]]:
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8873", timeout=180.0) as client:
        response = await client.get(TARGET_PATH, headers={"accept": "application/json"})
    try:
        payload = response.json()
    except Exception as exc:
        raise ProbeAbort("WORKSPACE_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise ProbeAbort("WORKSPACE_RESPONSE_NOT_OBJECT")
    return response.status_code, payload


def _safe_scalar(value: Any, limit: int = 180) -> str | int | bool | None:
    if isinstance(value, (str, int, bool)) or value is None:
        if isinstance(value, str) and (len(value) > limit or not re.fullmatch(r"[A-Za-z0-9._:/ -]*", value)):
            return hashlib.sha256(value.encode("utf-8")).hexdigest()
        return value
    return None


def _summary(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    product = payload.get("plan_product") if isinstance(payload.get("plan_product"), dict) else {}
    read_context = payload.get("read_context") if isinstance(payload.get("read_context"), dict) else {}
    plan_context = payload.get("plan_context") if isinstance(payload.get("plan_context"), dict) else {}
    attempt = payload.get("workspace_plan_attempt")
    attempt_summary: dict[str, Any] | None = None
    if isinstance(attempt, dict):
        attempt_summary = {key: _safe_scalar(attempt.get(key)) for key in SAFE_ATTEMPT_FIELDS if key in attempt}
        canonical = json.dumps(attempt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        attempt_summary["object_sha256"] = hashlib.sha256(canonical).hexdigest()
    contract = read_context.get("contract")
    if isinstance(contract, str):
        contract_summary: Any = _safe_scalar(contract)
    elif contract is not None:
        contract_summary = {"sha256": hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()}
    else:
        contract_summary = None
    run_id = product.get("run_id")
    reason = product.get("reason") or payload.get("reason")
    return {
        "target_date": TARGET_DATE,
        "http_status": status_code,
        "status": _safe_scalar(product.get("status") or payload.get("status") or read_context.get("status")),
        "reason": _safe_scalar(reason),
        "run_id": _safe_scalar(run_id),
        "expected_run_id_match": run_id == TARGET_RUN_ID,
        "plan_sha256": _safe_scalar(product.get("sha256")),
        "sealed_contract": contract_summary,
        "cutoff": _safe_scalar(plan_context.get("research_cutoff")),
        "attempt": attempt_summary,
        "read_mode": _safe_scalar(read_context.get("mode")),
        "candidate_count_known": read_context.get("candidate_count_known") if isinstance(read_context.get("candidate_count_known"), bool) else None,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-plist", type=Path, default=Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist"))
    parser.add_argument("--expected-pid", type=int, default=EXPECTED_PID)
    args = parser.parse_args()
    try:
        if args.expected_pid != EXPECTED_PID:
            raise ProbeAbort("EXPECTED_PID_OVERRIDE_FORBIDDEN")
        _env_values, launch = read_launch_configuration(args.active_plist, args.expected_pid)
        state_root_text = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
        if not state_root_text:
            raise ProbeAbort("MANAGER_RESEARCH_STATE_ROOT_MISSING")
        state_root = Path(state_root_text).expanduser()
        exact_plan = _existing_regular(state_root, f"workspace_plans/{TARGET_DATE}/{TARGET_RUN_ID}.json")
        latest_plan = _existing_regular(state_root, f"workspace_plans/{TARGET_DATE}/latest.json")
        exact_attempt = _existing_regular(state_root, f"workspace_plan_runs/{TARGET_DATE}/{TARGET_RUN_ID}.json")
        if max(exact_plan.st_size, latest_plan.st_size, exact_attempt.st_size) > MAX_PLAN_BYTES:
            raise ProbeAbort("TARGET_PLAN_INPUT_TOO_LARGE")
        identities_before = tuple((item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns) for item in (exact_plan, latest_plan, exact_attempt))

        # Install guards before candidate application modules are imported.
        install_write_guards()
        from apps.api.v35_api.app import create_app

        stage_root = launch.stage_selection_root or (Path(os.environ["V35_STAGE_CENTER_SELECTION_ROOT"]) if os.environ.get("V35_STAGE_CENTER_SELECTION_ROOT") else None)
        if not stage_root:
            raise ProbeAbort("ACTIVE_STAGE_ROOT_MISSING")
        app = create_app(
            data_root=launch.data_root or (Path(os.environ["V35_DATA_ROOT"]) if os.environ.get("V35_DATA_ROOT") else None),
            preselection_source_root=launch.preselection_source_root or (Path(os.environ["V35_PRESELECTION_SOURCE_ROOT"]) if os.environ.get("V35_PRESELECTION_SOURCE_ROOT") else None),
            shared_data_root=launch.shared_data_root or (Path(os.environ["V35_SHARED_DATA_ROOT"]) if os.environ.get("V35_SHARED_DATA_ROOT") else None),
            ledger_root=launch.ledger_root or (Path(os.environ["V35_DISPATCH_LEDGER_ROOT"]) if os.environ.get("V35_DISPATCH_LEDGER_ROOT") else None),
            stage_center_selection_root=stage_root,
        )
        code, payload = asyncio.run(_get_once(app))
        summary = _summary(code, payload)
        try:
            exact_plan_after = _existing_regular(state_root, f"workspace_plans/{TARGET_DATE}/{TARGET_RUN_ID}.json")
            latest_plan_after = _existing_regular(state_root, f"workspace_plans/{TARGET_DATE}/latest.json")
            exact_attempt_after = _existing_regular(state_root, f"workspace_plan_runs/{TARGET_DATE}/{TARGET_RUN_ID}.json")
        except ProbeAbort:
            raise ProbeAbort("TARGET_PLAN_INPUT_DISAPPEARED_DURING_READ")
        identities_after = tuple((item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns) for item in (exact_plan_after, latest_plan_after, exact_attempt_after))
        if identities_after != identities_before:
            raise ProbeAbort("TARGET_PLAN_INPUT_CHANGED_DURING_READ")
        summary["target_inputs_stable"] = True
        emit(**summary)
        return 0 if code == 200 and summary["expected_run_id_match"] else 2
    except ReadOnlyWriteBlocked as exc:
        emit(target_date=TARGET_DATE, status="BLOCKED", reason=exc.code, write_performed=False)
        return 3
    except ProbeAbort as exc:
        emit(target_date=TARGET_DATE, status="CANNOT_CONFIRM", reason=exc.code, write_performed=False)
        return 2
    except Exception as exc:
        emit(target_date=TARGET_DATE, status="CANNOT_CONFIRM", reason="UNEXPECTED_" + type(exc).__name__.upper(), write_performed=False)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
