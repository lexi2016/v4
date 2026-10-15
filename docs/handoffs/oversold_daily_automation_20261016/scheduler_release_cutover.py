"""Explicitly gated, CAS-bound scheduler activation and rollback helpers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import stat
import subprocess
import tempfile
import time
from typing import Any

DOC_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DOC_ROOT.parents[2]
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
CANDIDATE = BASE / "releases/oversold-daily-auto-20261016-r1"
STAGED_PLIST = CANDIDATE / "config/com.lexi.v35.scheduler.plist"
PREIMAGE = DOC_ROOT / "active_scheduler_plist.preimage"
PREP_RECEIPT = DOC_ROOT / "scheduler_release_preparation_receipt.json"
MANIFEST = CANDIDATE / "release-manifest.json"
ACTIVE_CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json")
ACTIVATION_RECEIPT = DOC_ROOT / "scheduler_release_activation_receipt.json"
ROLLBACK_RECEIPT = DOC_ROOT / "scheduler_release_rollback_receipt.json"
LABEL = "com.lexi.v35.scheduler"
LOCK_NAMES = (".com.lexi.v35.scheduler.release.lock", "com.lexi.v35.scheduler.release.lock")
WRITER_IDENTITY = "oversold_daily_writer"
RUNTIME_REVIEW_SCHEMA = "v4.oversold_daily_scheduler_runtime_review.v1"


class CutoverError(RuntimeError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CutoverError("JSON_OBJECT_REQUIRED")
    return value


def _launchctl_snapshot() -> dict[str, Any]:
    result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                            capture_output=True, text=True, timeout=10)
    values: dict[str, Any] = {"returncode": result.returncode}
    for key, expression in {
        "plist_path": r"^\s*path = ([^\r\n]+)",
        "program": r"^\s*program = ([^\r\n]+)",
        "working_directory": r"^\s*working directory = ([^\r\n]+)",
        "state": r"^\s*state = ([^\r\n]+)",
        "pid": r"^\s*pid = (\d+)",
    }.items():
        match = re.search(expression, result.stdout, re.MULTILINE)
        values[key] = (int(match.group(1)) if key == "pid" else match.group(1).strip()) if match else None
    return values


def _launchctl_print() -> tuple[int, str, int | None]:
    snapshot = _launchctl_snapshot()
    return snapshot["returncode"], str(snapshot.get("state") or ""), snapshot.get("pid")


def _pid_snapshot(pid: int) -> dict[str, Any]:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"exists": False, "pid": pid}
    except PermissionError as error:
        raise CutoverError("PROCESS_STATUS_UNAVAILABLE") from error
    result = subprocess.run(["/bin/ps", "-ww", "-p", str(pid), "-o", "pid=,command="],
                            capture_output=True, text=True, timeout=10)
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdecimal() and int(fields[0]) == pid:
            return {"exists": True, "pid": pid, "command": fields[1]}
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"exists": False, "pid": pid}
    except PermissionError as error:
        raise CutoverError("PROCESS_STATUS_UNAVAILABLE") from error
    raise CutoverError("PROCESS_COMMAND_UNAVAILABLE")


def _process_cwd(pid: int) -> Path:
    result = subprocess.run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                            capture_output=True, text=True, timeout=10)
    paths = [line[1:] for line in result.stdout.splitlines() if line.startswith("n") and len(line) > 1]
    if result.returncode != 0 or len(paths) != 1:
        raise CutoverError("PROCESS_CWD_UNAVAILABLE")
    return Path(paths[0]).resolve()


def _selector_evidence(expected_root: Path, selector_plist: Path) -> dict[str, Any]:
    expected_root = expected_root.resolve()
    try:
        job = plistlib.loads(selector_plist.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise CutoverError("SCHEDULER_SELECTOR_PLIST_UNREADABLE") from error
    if not isinstance(job, dict):
        raise CutoverError("SCHEDULER_SELECTOR_PLIST_INVALID")
    environment = job.get("EnvironmentVariables")
    arguments = job.get("ProgramArguments")
    if not isinstance(environment, dict) or not isinstance(arguments, list):
        raise CutoverError("SCHEDULER_SELECTOR_FIELDS_MISSING")

    # Read only the release selectors needed to bind the scheduler process. Never
    # dump the LaunchAgent environment, which may contain unrelated credentials.
    app_selector = environment.get("V35_APP_ROOT")
    release_id = environment.get("V35_RELEASE_ID")
    runtime_root = environment.get("V35_RUNTIME_ROOT")
    manifest_sha = environment.get("V35_RELEASE_MANIFEST_SHA256")
    pythonpath = environment.get("PYTHONPATH")
    config_selector = environment.get("V4_MANAGER_WORKBENCH_CONFIG_PATH")
    working_directory = job.get("WorkingDirectory")
    app_matches = isinstance(app_selector, str) and Path(app_selector).resolve() == expected_root
    release_matches = isinstance(release_id, str) and release_id == expected_root.parent.name
    runtime_valid = isinstance(runtime_root, str) and Path(runtime_root).is_absolute()
    pythonpath_items = pythonpath.split(os.pathsep) if isinstance(pythonpath, str) else []
    pythonpath_matches = (str(expected_root) in pythonpath_items
                          and str(expected_root / "upstreams") in pythonpath_items)
    config_matches = (isinstance(config_selector, str)
                      and Path(config_selector).resolve() == ACTIVE_CONFIG.resolve())
    working_directory_matches = (isinstance(working_directory, str)
                                 and Path(working_directory).resolve() == expected_root)
    launcher_matches = (len(arguments) >= 2 and arguments[0] == "/bin/bash"
                        and Path(str(arguments[1])).resolve()
                        == (expected_root / "ops/launch_v35_macos_scheduler.sh").resolve())
    manifest_path = expected_root.parent / "release-manifest.json"
    manifest_matches = (isinstance(manifest_sha, str) and manifest_path.is_file()
                        and file_sha(manifest_path) == manifest_sha)
    if not (app_matches and release_matches and runtime_valid and pythonpath_matches
            and config_matches and working_directory_matches and launcher_matches
            and isinstance(manifest_sha, str) and re.fullmatch(r"[0-9a-f]{64}", manifest_sha)
            and manifest_matches):
        raise CutoverError("SCHEDULER_RELEASE_SELECTOR_MISMATCH")
    return {
        "app_root": str(expected_root),
        "release_id": release_id,
        "runtime_root": runtime_root,
        "app_root_selector_match": True,
        "release_id_selector_match": True,
        "runtime_root_selector_valid": True,
        "pythonpath_selector_match": True,
        "manager_config_selector_match": True,
        "working_directory_selector_match": True,
        "launcher_selector_match": True,
        "release_manifest_selector_match": True,
    }


def _process_identity_for_root(pid: int, expected_root: Path, *,
                               selector_plist: Path = PLIST,
                               job_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    expected_root = expected_root.resolve()
    selector = _selector_evidence(expected_root, selector_plist)
    snapshot = _pid_snapshot(pid)
    if not snapshot["exists"]:
        raise CutoverError("SCHEDULER_PROCESS_NOT_RUNNING")
    command = str(snapshot.get("command") or "")
    python_path = Path(str(selector["runtime_root"])) / "venvs/v3.5-mac/bin/python"
    prefix = f"{python_path} -S -m "
    if not command.startswith(prefix):
        raise CutoverError("SCHEDULER_INTERPRETER_COMMAND_MISMATCH")
    module_and_args = shlex.split(command[len(prefix):])
    if not module_and_args or module_and_args[0] != "ops.run_v35_macos_scheduler_daemon":
        raise CutoverError("SCHEDULER_DAEMON_MODULE_MISMATCH")
    process_cwd = _process_cwd(pid)
    if process_cwd != expected_root:
        raise CutoverError("SCHEDULER_PROCESS_CWD_MISMATCH")
    evidence: dict[str, Any] = {
        "pid": pid,
        "label": LABEL,
        "process_cwd": str(process_cwd),
        "interpreter_command_match": True,
        "daemon_module_match": True,
        **selector,
    }
    if job_snapshot is not None:
        if (job_snapshot.get("returncode") != 0 or job_snapshot.get("state") != "running"
                or job_snapshot.get("pid") != pid):
            raise CutoverError("LAUNCHD_LABEL_PID_MISMATCH")
        if Path(str(job_snapshot.get("plist_path") or "")).resolve() != PLIST.resolve():
            raise CutoverError("LAUNCHD_LABEL_PLIST_MISMATCH")
        if (job_snapshot.get("program") != "/bin/bash"
                or Path(str(job_snapshot.get("working_directory") or "")).resolve() != expected_root):
            raise CutoverError("LAUNCHD_LABEL_SELECTOR_MISMATCH")
        evidence.update({
            "launchd_label_pid_match": True,
            "launchd_plist_path_match": True,
            "launchd_program_match": True,
            "launchd_working_directory_match": True,
        })
    return evidence


def _scheduler_processes_for_root(root: Path, selector_plist: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    result = subprocess.run(["/bin/ps", "-ww", "-axo", "pid=,command="],
                            capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise CutoverError("PROCESS_TABLE_UNAVAILABLE")
    selector = _selector_evidence(root, selector_plist)
    python_path = Path(str(selector["runtime_root"])) / "venvs/v3.5-mac/bin/python"
    prefix = f"{python_path} -S -m ops.run_v35_macos_scheduler_daemon"
    module_marker = " -m ops.run_v35_macos_scheduler_daemon"
    matches = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdecimal():
            continue
        pid, command = int(fields[0]), fields[1]
        if module_marker in command and _process_cwd(pid) == root:
            matches.append({"pid": pid, "root_match": True, "process_cwd_match": True,
                            "daemon_module_match": True,
                            "configured_interpreter_match": command.startswith(prefix)})
    return matches


def _launchctl(action: str, *arguments: str) -> int:
    result = subprocess.run(["/bin/launchctl", action, *arguments],
                            capture_output=True, text=True, timeout=30)
    return result.returncode


def _wait_detached(old_pid: int, expected_root: Path, *, timeout_seconds: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = _launchctl_snapshot()
        old_process = _pid_snapshot(old_pid)
        if job["returncode"] != 0 and not old_process["exists"]:
            time.sleep(3.0)
            final_job = _launchctl_snapshot()
            final_process = _pid_snapshot(old_pid)
            if final_job["returncode"] != 0 and not final_process["exists"]:
                return {"old_pid": old_pid, "expected_app_root": str(expected_root.resolve()),
                        "old_pid_absent": True, "old_process_exited": True, "label_absent": True,
                        "settle_seconds": 3}
        time.sleep(0.5)
    raise CutoverError("SERVICE_DETACH_NOT_CONFIRMED")


def _wait_attached(expected_root: Path, *, selector_plist: Path = PLIST,
                   timeout_seconds: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = _launchctl_snapshot()
        pid = job.get("pid")
        if job["returncode"] == 0 and job.get("state") == "running" and pid is not None:
            try:
                evidence = _process_identity_for_root(pid, expected_root, selector_plist=selector_plist,
                                                      job_snapshot=job)
            except CutoverError:
                time.sleep(0.5)
                continue
            return {"pid": pid, "state": job["state"], "process_identity": evidence}
        time.sleep(0.5)
    raise CutoverError("SERVICE_ATTACH_NOT_CONFIRMED")


def _atomic_install(raw: bytes, mode: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".com.lexi.v35.scheduler.oversold-", dir=PLIST.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, PLIST)
        directory_fd = os.open(PLIST.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _locks():
    from infrastructure.interprocess_lock import owned_interprocess_lock
    from contextlib import ExitStack
    stack = ExitStack()
    leases = []
    for name in LOCK_NAMES:
        lock_path = PLIST.with_name(name)
        leases.append(stack.enter_context(owned_interprocess_lock(
            lock_path, timeout_seconds=3.0, timeout_message="SCHEDULER_RELEASE_LOCK_BUSY")))
    return stack, leases


def _assert_leases(leases: list[object]) -> None:
    from infrastructure.interprocess_lock import assert_owned_interprocess_lock
    for lease, name in zip(leases, LOCK_NAMES):
        assert_owned_interprocess_lock(lease, PLIST.with_name(name))


def _prepared() -> dict[str, Any]:
    receipt = _read_json(PREP_RECEIPT)
    if receipt.get("status") != "PREPARED_NOT_ACTIVATED":
        raise CutoverError("PREPARATION_RECEIPT_NOT_READY")
    if receipt.get("candidate_release_id") != CANDIDATE.name:
        raise CutoverError("CANDIDATE_RELEASE_ID_MISMATCH")
    if (file_sha(MANIFEST) != receipt.get("candidate_release_manifest_sha256")
            or file_sha(STAGED_PLIST) != receipt.get("candidate_staged_plist_sha256")):
        raise CutoverError("CANDIDATE_HASH_CHANGED")
    if file_sha(ACTIVE_CONFIG) != receipt.get("base_manager_config_sha256"):
        raise CutoverError("ACTIVE_MANAGER_CONFIG_CAS_CHANGED")
    if not PREIMAGE.is_file() or PREIMAGE.read_bytes() != PLIST.read_bytes():
        raise CutoverError("ACTIVE_PLIST_PREIMAGE_MISMATCH")
    if file_sha(PREIMAGE) != receipt.get("base_plist_preimage_sha256"):
        raise CutoverError("SAVED_PLIST_PREIMAGE_SHA_MISMATCH")
    return receipt


def _require_runtime_review(path: Path, manifest_sha: str) -> str:
    review = _read_json(path)
    if review.get("schema_version") != RUNTIME_REVIEW_SCHEMA or review.get("status") != "PASS_RUNTIME_RELEASE":
        raise CutoverError("RUNTIME_RELEASE_REVIEW_PASS_REQUIRED")
    if review.get("behavior_verified") != "PASS":
        raise CutoverError("RUNTIME_BEHAVIOR_VERIFICATION_REQUIRED")
    reviewer = str(review.get("reviewer_identity", "")).strip().casefold()
    writer = str(review.get("writer_identity", "")).strip().casefold()
    if not reviewer or reviewer == writer or writer != WRITER_IDENTITY.casefold():
        raise CutoverError("RUNTIME_REVIEWER_IDENTITY_NOT_INDEPENDENT")
    if review.get("candidate_release_manifest_sha256") != manifest_sha:
        raise CutoverError("RUNTIME_REVIEW_CANDIDATE_SHA_MISMATCH")
    return file_sha(path)


def _record(path: Path, receipt: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    path.chmod(0o600)


def activate(*, authorization_ref: str, runtime_review_path: Path) -> dict[str, Any]:
    if not authorization_ref.strip():
        raise CutoverError("EXPLICIT_ACTIVATION_AUTHORIZATION_REFERENCE_REQUIRED")
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    receipt = _prepared()
    review_sha = _require_runtime_review(runtime_review_path, receipt["candidate_release_manifest_sha256"])
    stack, leases = _locks()
    result: dict[str, Any] = {
        "schema_version": "v4.oversold_daily_scheduler_activation_receipt.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "PREFLIGHT",
        "activation_authorization_ref": authorization_ref,
        "runtime_review_path": str(runtime_review_path),
        "runtime_review_sha256": review_sha,
        "candidate_release_manifest_sha256": receipt["candidate_release_manifest_sha256"],
        "candidate_staged_plist_sha256": receipt["candidate_staged_plist_sha256"],
        "commands": [],
        "launchctl_called": False,
    }
    original = PREIMAGE.read_bytes()
    mode = int(receipt["base_plist_preimage_mode"], 8)
    base_root = Path(receipt["base_release_root"])
    candidate_root = CANDIDATE / "app"
    try:
        if file_sha(PLIST) != receipt["base_plist_preimage_sha256"]:
            raise CutoverError("ACTIVE_PLIST_CAS_CHANGED_REBASE_REQUIRED")
        if file_sha(ACTIVE_CONFIG) != receipt["base_manager_config_sha256"]:
            raise CutoverError("ACTIVE_MANAGER_CONFIG_CAS_CHANGED")
        from ops.api_release_integration import inventory_digest, inventory_tree
        if inventory_digest(inventory_tree(base_root / "app")) != _read_json(base_root / "release-manifest.json")["application_inventory"]["aggregate_sha256"]:
            raise CutoverError("ACTIVE_BASE_RELEASE_INVENTORY_CHANGED")
        if inventory_digest(inventory_tree(CANDIDATE / "app")) != _read_json(MANIFEST)["application_inventory"]["aggregate_sha256"]:
            raise CutoverError("CANDIDATE_RELEASE_INVENTORY_CHANGED")
        active_job = _launchctl_snapshot()
        old_pid = active_job.get("pid")
        if active_job["returncode"] != 0 or active_job.get("state") != "running" or old_pid is None:
            raise CutoverError("ACTIVE_SCHEDULER_NOT_RUNNING")
        base_process_identity = _process_identity_for_root(
            old_pid, base_root / "app", selector_plist=PLIST, job_snapshot=active_job)
        _assert_leases(leases)
        result["preflight"] = {"base_release_id": receipt["base_release_id"], "old_pid": old_pid,
                                "active_plist_sha256": file_sha(PLIST),
                                "manager_config_sha256": file_sha(ACTIVE_CONFIG),
                                "candidate_release_inventory_verified": True,
                                "process_identity": base_process_identity}
        result["commands"].append({"action": "bootout", "label": LABEL,
                                   "exit_code": _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")})
        result["launchctl_called"] = True
        detached = _wait_detached(old_pid, base_root / "app")
        result["detach"] = detached
        _assert_leases(leases)
        if file_sha(PLIST) != receipt["base_plist_preimage_sha256"]:
            raise CutoverError("ACTIVE_PLIST_CAS_CHANGED_AFTER_DETACH")
        _atomic_install(STAGED_PLIST.read_bytes(), mode)
        result["active_plist_sha256"] = file_sha(PLIST)
        if result["active_plist_sha256"] != receipt["candidate_staged_plist_sha256"]:
            raise CutoverError("ACTIVE_CANDIDATE_PLIST_INSTALL_MISMATCH")
        bootstrap_code = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
        result["commands"].append({"action": "bootstrap", "label": LABEL, "exit_code": bootstrap_code})
        if bootstrap_code != 0:
            raise CutoverError("CANDIDATE_BOOTSTRAP_FAILED")
        result["launchctl_called"] = True
        result["attach"] = _wait_attached(candidate_root)
        result["status"] = "ACTIVATED_RUNTIME_ONLY"
        result["activation_status"] = "ACTIVATED"
        result["deployment_status"] = "CANNOT_CONFIRM"
        result["api_ui_and_natural_slot"] = "CANNOT_CONFIRM"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        _record(ACTIVATION_RECEIPT, result)
        return result
    except Exception as error:
        result["failure_code"] = str(error).split(":", 1)[0]
        # If the candidate pointer was installed, restore only after the candidate process and label drain.
        if PLIST.exists() and file_sha(PLIST) == receipt["candidate_staged_plist_sha256"]:
            code, _state, pid = _launchctl_print()
            if code == 0 and pid is not None:
                result["commands"].append({"action": "bootout_candidate", "label": LABEL,
                                           "exit_code": _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")})
                result["launchctl_called"] = True
                try:
                    result["candidate_detach"] = _wait_detached(pid, candidate_root)
                except Exception:
                    result["status"] = "FAILED_CANDIDATE_STILL_ATTACHED_ROLLBACK_BLOCKED"
                    result["finished_at"] = datetime.now(timezone.utc).isoformat()
                    _record(ACTIVATION_RECEIPT, result)
                    stack.close()
                    raise
            elif _scheduler_processes_for_root(candidate_root, STAGED_PLIST):
                result["status"] = "FAILED_CANDIDATE_PROCESS_WITH_LABEL_ABSENT_ROLLBACK_BLOCKED"
                result["finished_at"] = datetime.now(timezone.utc).isoformat()
                _record(ACTIVATION_RECEIPT, result)
                stack.close()
                raise CutoverError("CANDIDATE_PROCESS_REMAINS_WITH_LABEL_ABSENT") from error
            _atomic_install(original, mode)
        code, _state, _pid = _launchctl_print()
        if code != 0:
            old_bootstrap = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
            result["commands"].append({"action": "bootstrap_preimage", "label": LABEL,
                                       "exit_code": old_bootstrap})
            result["launchctl_called"] = True
        try:
            result["rollback_to_preimage"] = _wait_attached(base_root / "app")
            result["status"] = "FAILED_RESTORED_BASE_RUNTIME"
        except Exception:
            result["status"] = "FAILED_RESTORE_RUNTIME_CANNOT_CONFIRM"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        _record(ACTIVATION_RECEIPT, result)
        raise
    finally:
        stack.close()


def rollback(*, authorization_ref: str) -> dict[str, Any]:
    if not authorization_ref.strip():
        raise CutoverError("EXPLICIT_ROLLBACK_AUTHORIZATION_REFERENCE_REQUIRED")
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    receipt = _read_json(PREP_RECEIPT)
    if receipt.get("status") != "PREPARED_NOT_ACTIVATED":
        raise CutoverError("PREPARATION_RECEIPT_NOT_READY")
    if file_sha(STAGED_PLIST) != receipt.get("candidate_staged_plist_sha256"):
        raise CutoverError("CANDIDATE_PLIST_HASH_CHANGED")
    if file_sha(MANIFEST) != receipt.get("candidate_release_manifest_sha256"):
        raise CutoverError("CANDIDATE_MANIFEST_HASH_CHANGED")
    if file_sha(ACTIVE_CONFIG) != receipt.get("base_manager_config_sha256"):
        raise CutoverError("ACTIVE_MANAGER_CONFIG_CAS_CHANGED")
    if not PREIMAGE.is_file() or file_sha(PREIMAGE) != receipt.get("base_plist_preimage_sha256"):
        raise CutoverError("SAVED_PLIST_PREIMAGE_SHA_MISMATCH")
    stack, leases = _locks()
    original = PREIMAGE.read_bytes()
    mode = int(receipt["base_plist_preimage_mode"], 8)
    base_root = Path(receipt["base_release_root"])
    candidate_root = CANDIDATE / "app"
    if not ACTIVATION_RECEIPT.is_file():
        raise CutoverError("ACTIVATION_RECEIPT_REQUIRED_FOR_ROLLBACK")
    activation = _read_json(ACTIVATION_RECEIPT)
    if (activation.get("status") != "ACTIVATED_RUNTIME_ONLY"
            or activation.get("candidate_release_manifest_sha256") != receipt.get("candidate_release_manifest_sha256")
            or activation.get("candidate_staged_plist_sha256") != receipt.get("candidate_staged_plist_sha256")):
        raise CutoverError("SUCCESSFUL_ACTIVATION_RECEIPT_MISMATCH")
    result: dict[str, Any] = {
        "schema_version": "v4.oversold_daily_scheduler_rollback_receipt.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "PREFLIGHT",
        "rollback_authorization_ref": authorization_ref,
        "base_plist_preimage_sha256": receipt["base_plist_preimage_sha256"],
        "candidate_staged_plist_sha256": receipt["candidate_staged_plist_sha256"],
        "commands": [],
        "launchctl_called": False,
    }
    try:
        if file_sha(PLIST) != receipt["candidate_staged_plist_sha256"]:
            raise CutoverError("ACTIVE_PLIST_NOT_EXACT_CANDIDATE_CAS")
        active_job = _launchctl_snapshot()
        code, state, pid = active_job["returncode"], active_job.get("state"), active_job.get("pid")
        if code == 0:
            if state != "running" or pid is None:
                raise CutoverError("ACTIVE_CANDIDATE_SCHEDULER_STATE_AMBIGUOUS")
            result["preflight_process_identity"] = _process_identity_for_root(
                pid, candidate_root, selector_plist=STAGED_PLIST, job_snapshot=active_job)
        else:
            candidate_processes = _scheduler_processes_for_root(candidate_root, STAGED_PLIST)
            base_processes = _scheduler_processes_for_root(base_root / "app", PREIMAGE)
            if candidate_processes or base_processes:
                raise CutoverError("SCHEDULER_PROCESS_REMAINS_WITH_LABEL_ABSENT")
            result["detach"] = {"label_absent": True, "candidate_processes": [], "base_processes": []}
        _assert_leases(leases)
        if code == 0:
            result["commands"].append({"action": "bootout_candidate", "label": LABEL,
                                       "exit_code": _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")})
            result["launchctl_called"] = True
            result["detach"] = _wait_detached(pid, candidate_root)
        _assert_leases(leases)
        if file_sha(PLIST) != receipt["candidate_staged_plist_sha256"]:
            raise CutoverError("ACTIVE_PLIST_CAS_CHANGED_AFTER_DETACH")
        _atomic_install(original, mode)
        if file_sha(PLIST) != receipt["base_plist_preimage_sha256"]:
            raise CutoverError("ROLLBACK_PLIST_INSTALL_MISMATCH")
        bootstrap_code = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
        result["commands"].append({"action": "bootstrap_preimage", "label": LABEL, "exit_code": bootstrap_code})
        if bootstrap_code != 0:
            raise CutoverError("BASE_RUNTIME_BOOTSTRAP_FAILED")
        result["launchctl_called"] = True
        result["attach"] = _wait_attached(base_root / "app")
        result["status"] = "ROLLED_BACK_BASE_RUNTIME_ONLY"
        result["activation_status"] = "CANDIDATE_DEACTIVATED"
        result["deployment_status"] = "CANNOT_CONFIRM"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        _record(ROLLBACK_RECEIPT, result)
        return result
    finally:
        stack.close()


def main(mode: str) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(f"--{mode}", action="store_true", help=f"execute {mode}; requires separate authorization")
    parser.add_argument("--authorization-ref")
    parser.add_argument("--runtime-review", type=Path)
    args = parser.parse_args()
    try:
        if not getattr(args, mode):
            print(json.dumps({"status": "PREPARED_ONLY", "launchctl_called": False,
                              "helper_mode": mode, "requires_explicit_authorization": True}, sort_keys=True))
            return 0
        if mode == "activate":
            if args.runtime_review is None:
                raise CutoverError("RUNTIME_RELEASE_REVIEW_RECEIPT_REQUIRED")
            value = activate(authorization_ref=args.authorization_ref or "", runtime_review_path=args.runtime_review)
        else:
            value = rollback(authorization_ref=args.authorization_ref or "")
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    except (CutoverError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"CUTOVER_BLOCKED: {type(error).__name__}:{str(error)[:240]}\n")


if __name__ == "__main__":
    raise SystemExit("Use activate_scheduler_release.py or rollback_scheduler_release.py")
