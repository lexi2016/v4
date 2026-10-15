#!/usr/bin/env python3
"""Plan-only by default; optionally resume the exact 20261015 -> 20261016 owner."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

DOC_ROOT = Path(__file__).resolve().parent
OVERSOLD_CANDIDATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-auto-20261016-r1")
ACTIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
ACTIVE_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-scheduler-20261016-r4")
ACTIVE_APP_ROOT = ACTIVE_RELEASE_ROOT / "app"
ACTIVE_CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json")
ACTIVE_RUNTIME_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime")
ACTIVE_RELEASE_ID = "zsxq-pdf-ocr-scheduler-20261016-r4"
ACTIVE_PID = 32762
ACTIVE_PLIST_SHA256 = "e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72"
ACTIVE_MANIFEST_SHA256 = "4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91"
ACTIVE_CONFIG_SHA256 = "65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca"
OVERSOLD_CANDIDATE_MANIFEST_SHA256 = "d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6"
OVERSOLD_CANDIDATE_PLIST_SHA256 = "91d83bd16af4b7932fb07007651339ee3978aa8a293d72e25e828962c8403072"
ACTIVE_SOURCE_SHA256 = {
    "v4/manager_workbench/scheduler.py": "0672296a340ae84d6bfb48b77b8d23566ea32b4fdb27edc505ea3abb4d785990",
    "v4/manager_workbench/inputs/source_bindings.py": "4e9339675d544a5f57e0fe6c5bc5522fba7b9aac6fdc21d6967082cfb7729edb",
    "v4/manager_workbench/service.py": "338544fc7876170e05566b5df90c31058a275fa8076f6474b80ab2bd7e19997e",
    "v4/manager_workbench/store.py": "493df1a72bf4c4a533ae533ce5fc0185c9d9536d01c4e88082270908c8b1aa18",
    "v4/manager_workbench/oversold_daily.py": "1a88ac9c1bb3e1a2d68fff350a69204a65b7ebb782f27512bb4fc1c45f9b0583",
    "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py": "62513b42bcd133d3c447b9b797b81c19f43a306c9544ce97a11447db93b54e9e",
}
ACTIVATION_RECEIPT = DOC_ROOT / "scheduler_release_activation_receipt.json"
TARGET_DATE = "20261016"
SOURCE_DAY = "20261015"
HK = ZoneInfo("Asia/Hong_Kong")
MAX_WAIT_SECONDS = 3600
LABEL = "com.lexi.v35.scheduler"


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _active_launchd_snapshot() -> dict[str, object]:
    result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                            capture_output=True, text=True, timeout=10)
    snapshot: dict[str, object] = {"returncode": result.returncode}
    for key, pattern in {
        "plist_path": r"^\s*path = ([^\r\n]+)",
        "program": r"^\s*program = ([^\r\n]+)",
        "working_directory": r"^\s*working directory = ([^\r\n]+)",
        "state": r"^\s*state = ([^\r\n]+)",
        "pid": r"^\s*pid = (\d+)",
    }.items():
        match = re.search(pattern, result.stdout, re.MULTILINE)
        snapshot[key] = (int(match.group(1)) if key == "pid" else match.group(1).strip()) if match else None
    return snapshot


def _active_process_command(pid: int) -> str:
    result = subprocess.run(["/bin/ps", "-ww", "-p", str(pid), "-o", "pid=,command="],
                            capture_output=True, text=True, timeout=10)
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdecimal() and int(fields[0]) == pid:
            return fields[1]
    raise RuntimeError("ACTIVE_SCHEDULER_PROCESS_COMMAND_UNAVAILABLE")


def _active_process_cwd(pid: int) -> Path:
    result = subprocess.run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                            capture_output=True, text=True, timeout=10)
    paths = [line[1:] for line in result.stdout.splitlines() if line.startswith("n") and len(line) > 1]
    if result.returncode != 0 or len(paths) != 1:
        raise RuntimeError("ACTIVE_SCHEDULER_PROCESS_CWD_UNAVAILABLE")
    return Path(paths[0]).resolve()


def _validate_active_scheduler_identity() -> dict[str, object]:
    """Fail closed unless the one independently reviewed inherited release is active."""
    if not ACTIVE_PLIST.is_file() or _sha(ACTIVE_PLIST) != ACTIVE_PLIST_SHA256:
        raise RuntimeError("ACTIVE_SCHEDULER_PLIST_SHA_MISMATCH")
    if not ACTIVE_CONFIG.is_file() or _sha(ACTIVE_CONFIG) != ACTIVE_CONFIG_SHA256:
        raise RuntimeError("ACTIVE_MANAGER_CONFIG_SHA_MISMATCH")

    try:
        job = plistlib.loads(ACTIVE_PLIST.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise RuntimeError("ACTIVE_SCHEDULER_PLIST_UNREADABLE") from error
    if not isinstance(job, dict):
        raise RuntimeError("ACTIVE_SCHEDULER_PLIST_INVALID")
    environment = job.get("EnvironmentVariables")
    arguments = job.get("ProgramArguments")
    if not isinstance(environment, dict) or not isinstance(arguments, list):
        raise RuntimeError("ACTIVE_SCHEDULER_PLIST_SELECTORS_MISSING")

    expected_pythonpath = f"{ACTIVE_APP_ROOT}/upstreams{os.pathsep}{ACTIVE_APP_ROOT}"
    expected_arguments = ["/bin/bash", str(ACTIVE_APP_ROOT / "ops/launch_v35_macos_scheduler.sh")]
    selector_ok = (
        environment.get("V35_APP_ROOT") == str(ACTIVE_APP_ROOT)
        and environment.get("V35_RELEASE_ID") == ACTIVE_RELEASE_ID
        and environment.get("V35_RUNTIME_ROOT") == str(ACTIVE_RUNTIME_ROOT)
        and environment.get("V35_RELEASE_MANIFEST_SHA256") == ACTIVE_MANIFEST_SHA256
        and environment.get("PYTHONPATH") == expected_pythonpath
        and environment.get("V4_MANAGER_WORKBENCH_CONFIG_PATH") == str(ACTIVE_CONFIG)
        and job.get("WorkingDirectory") == str(ACTIVE_APP_ROOT)
        and arguments == expected_arguments
    )
    if not selector_ok:
        raise RuntimeError("ACTIVE_SCHEDULER_PLIST_SELECTOR_MISMATCH")

    manifest_path = ACTIVE_RELEASE_ROOT / "release-manifest.json"
    if not manifest_path.is_file() or _sha(manifest_path) != ACTIVE_MANIFEST_SHA256:
        raise RuntimeError("ACTIVE_SCHEDULER_MANIFEST_SHA_MISMATCH")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("ACTIVE_SCHEDULER_MANIFEST_UNREADABLE") from error
    base = manifest.get("base")
    candidate = manifest.get("candidate")
    if (manifest.get("role") != "scheduler" or not isinstance(base, dict)
            or base.get("manifest_sha256") != OVERSOLD_CANDIDATE_MANIFEST_SHA256
            or base.get("plist_sha256") != OVERSOLD_CANDIDATE_PLIST_SHA256
            or base.get("app_root") != str(OVERSOLD_CANDIDATE / "app")
            or not isinstance(candidate, dict)
            or candidate.get("release_id") != ACTIVE_RELEASE_ID
            or candidate.get("root") != str(ACTIVE_RELEASE_ROOT)
            or candidate.get("app_root") != str(ACTIVE_APP_ROOT)):
        raise RuntimeError("ACTIVE_SCHEDULER_RELEASE_LINEAGE_MISMATCH")

    inventory = manifest.get("application_inventory")
    entries = inventory.get("entries") if isinstance(inventory, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError("ACTIVE_SCHEDULER_MANIFEST_INVENTORY_MISSING")
    for relative_path, expected_sha in ACTIVE_SOURCE_SHA256.items():
        matches = [entry for entry in entries
                   if isinstance(entry, dict) and entry.get("path") == relative_path]
        source_path = ACTIVE_APP_ROOT / relative_path
        if len(matches) != 1 or matches[0].get("sha256") != expected_sha:
            raise RuntimeError("ACTIVE_SCHEDULER_MANIFEST_SOURCE_SHA_MISMATCH")
        if not source_path.is_file() or _sha(source_path) != expected_sha:
            raise RuntimeError("ACTIVE_SCHEDULER_SOURCE_SHA_MISMATCH")

    launchd = _active_launchd_snapshot()
    if (launchd.get("returncode") != 0 or launchd.get("state") != "running"
            or launchd.get("pid") != ACTIVE_PID):
        raise RuntimeError("ACTIVE_SCHEDULER_LABEL_PID_MISMATCH")
    if Path(str(launchd.get("plist_path") or "")).resolve() != ACTIVE_PLIST.resolve():
        raise RuntimeError("ACTIVE_SCHEDULER_LABEL_PLIST_MISMATCH")
    if (launchd.get("program") != "/bin/bash"
            or Path(str(launchd.get("working_directory") or "")).resolve() != ACTIVE_APP_ROOT.resolve()):
        raise RuntimeError("ACTIVE_SCHEDULER_LABEL_SELECTOR_MISMATCH")

    command = _active_process_command(ACTIVE_PID)
    expected_python = str(ACTIVE_RUNTIME_ROOT / "venvs/v3.5-mac/bin/python")
    expected_command_prefix = f"{expected_python} -S -m ops.run_v35_macos_scheduler_daemon"
    if not (command == expected_command_prefix or command.startswith(expected_command_prefix + " ")):
        raise RuntimeError("ACTIVE_SCHEDULER_PROCESS_COMMAND_MISMATCH")
    process_cwd = _active_process_cwd(ACTIVE_PID)
    if process_cwd != ACTIVE_APP_ROOT.resolve():
        raise RuntimeError("ACTIVE_SCHEDULER_PROCESS_CWD_MISMATCH")

    return {
        "label": LABEL,
        "pid": ACTIVE_PID,
        "release_id": ACTIVE_RELEASE_ID,
        "release_root": str(ACTIVE_RELEASE_ROOT),
        "app_root": str(ACTIVE_APP_ROOT),
        "plist_sha256": ACTIVE_PLIST_SHA256,
        "manifest_sha256": ACTIVE_MANIFEST_SHA256,
        "manager_config_sha256": ACTIVE_CONFIG_SHA256,
        "source_sha256": ACTIVE_SOURCE_SHA256,
        "launchd_label_pid_match": True,
        "process_interpreter_module_match": True,
        "process_cwd": str(process_cwd),
        "active_release_identity": "VERIFIED_EXACT_INHERITED_R4",
    }


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _context_matches_legacy_nextday(context, source_day: str, target_date: str) -> bool:
    scope_refs = getattr(context, "scope_refs", None)
    if not isinstance(scope_refs, dict):
        return False
    requested_lanes = scope_refs.get("requested_lanes")
    return (
        getattr(context, "target_date", None) == target_date
        and _value(getattr(context, "phase", None)) == "NEXT_DAY"
        and _value(getattr(context, "trigger", None)) == "SCHEDULED"
        and scope_refs.get("source_hk_session") == source_day
        and isinstance(requested_lanes, list)
        and "OVERSOLD" in {_value(lane) for lane in requested_lanes}
    )


def _validate_legacy_nextday_bridge(service, source_day: str, target_date: str) -> dict[str, str]:
    """Authorize a real driver bootstrap only from the exact completed legacy partial."""
    from v4.manager_workbench.contracts import digest

    configured_lanes = getattr(service.config, "scheduled_lanes", None)
    if not isinstance(configured_lanes, (list, tuple)) or not configured_lanes:
        raise RuntimeError("LEGACY_NEXTDAY_SCOPE_UNAVAILABLE")
    lane_values = sorted(str(_value(lane)) for lane in configured_lanes)
    if "OVERSOLD" not in lane_values:
        raise RuntimeError("LEGACY_NEXTDAY_OVERSOLD_SCOPE_MISSING")

    legacy_key = f"nextday_{source_day}_{digest(lane_values)[:16]}"
    legacy_cursor = service.store.cursor(legacy_key)
    if not isinstance(legacy_cursor, dict):
        raise RuntimeError("LEGACY_NEXTDAY_CURSOR_MISSING")
    if legacy_cursor.get("target_date") != target_date:
        raise RuntimeError("LEGACY_NEXTDAY_CURSOR_TARGET_MISMATCH")
    job_id = legacy_cursor.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise RuntimeError("LEGACY_NEXTDAY_JOB_ID_MISSING")

    job = service.store.get_job(job_id)
    if job is None or getattr(job, "job_id", None) != job_id:
        raise RuntimeError("LEGACY_NEXTDAY_JOB_MISSING")
    job_state = str(_value(getattr(job, "state", "")))
    terminal_job_states = {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}
    if job_state in {"QUEUED", "RUNNING"}:
        raise RuntimeError("LEGACY_NEXTDAY_JOB_STILL_RUNNING")
    if job_state not in terminal_job_states or not getattr(job, "finished_at", None):
        raise RuntimeError("LEGACY_NEXTDAY_JOB_NOT_COMPLETED")
    run_id = getattr(job, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise RuntimeError("LEGACY_NEXTDAY_RUN_ID_MISSING")
    if not _context_matches_legacy_nextday(getattr(job, "context", None), source_day, target_date):
        raise RuntimeError("LEGACY_NEXTDAY_JOB_CONTEXT_MISMATCH")

    try:
        plan = service.store.read_plan(run_id)
    except (KeyError, ValueError) as error:
        raise RuntimeError("LEGACY_NEXTDAY_PLAN_MISSING") from error
    if getattr(plan, "run_id", None) != run_id:
        raise RuntimeError("LEGACY_NEXTDAY_PLAN_RUN_MISMATCH")
    context = getattr(plan, "context", None)
    if not _context_matches_legacy_nextday(context, source_day, target_date):
        raise RuntimeError("LEGACY_NEXTDAY_PLAN_CONTEXT_MISMATCH")
    oversold_lanes = [
        lane for lane in getattr(plan, "lanes", [])
        if _value(getattr(lane, "lane", None)) == "OVERSOLD"
    ]
    if len(oversold_lanes) != 1:
        raise RuntimeError("LEGACY_NEXTDAY_OVERSOLD_LANE_MISSING_OR_DUPLICATE")
    lane_state = str(_value(getattr(oversold_lanes[0], "state", "")))
    if lane_state != "INPUT_MISSING":
        raise RuntimeError("LEGACY_NEXTDAY_OVERSOLD_NOT_INPUT_MISSING")

    return {
        "legacy_cursor_key": legacy_key,
        "job_id": job_id,
        "run_id": run_id,
        "job_state": job_state,
        "job_finished_at": str(job.finished_at),
        "source_hk_session": source_day,
        "target_date": target_date,
        "phase": "NEXT_DAY",
        "oversold_lane_state": lane_state,
    }


def _recovery_cursor_preflight(service, key: str, source_day: str, target_date: str):
    initial = service.store.cursor(key)
    if initial is None:
        bridge = _validate_legacy_nextday_bridge(service, source_day, target_date)
        return None, bridge
    if not isinstance(initial, dict):
        raise RuntimeError("EXISTING_CURSOR_INVALID")
    if initial.get("source_hk_session") != source_day or initial.get("target_date") != target_date:
        raise RuntimeError("EXISTING_CURSOR_IDENTITY_MISMATCH")
    return initial, None


def _child(args: argparse.Namespace) -> int:
    from v4.manager_workbench.binding import create_native_binding
    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import HK as WORKBENCH_HK
    from v4.manager_workbench.service import create_service

    active_identity = _validate_active_scheduler_identity()
    candidate_manifest = OVERSOLD_CANDIDATE / "release-manifest.json"
    activation = json.loads(ACTIVATION_RECEIPT.read_text(encoding="utf-8"))
    if (activation.get("status") != "ACTIVATED_RUNTIME_ONLY"
            or not candidate_manifest.is_file()
            or _sha(candidate_manifest) != OVERSOLD_CANDIDATE_MANIFEST_SHA256
            or activation.get("candidate_release_manifest_sha256") != OVERSOLD_CANDIDATE_MANIFEST_SHA256):
        raise RuntimeError("OVERSOLD_CANDIDATE_ACTIVATION_RECEIPT_MISMATCH")
    if datetime.now(HK).strftime("%Y%m%d") != TARGET_DATE:
        raise RuntimeError("TARGET_DATE_IS_NOT_CURRENT_HK_SESSION")
    config_path = os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", "").strip()
    if not config_path:
        raise RuntimeError("EXISTING_MANAGER_CONFIG_BINDING_MISSING")
    config = load_config(config_path)
    binding = create_native_binding(config)
    service = create_service(config, binding["adapters"], binding["engines"], binding["executor"],
                             capture_transport=binding.get("capture_transport"),
                             capture_clock=binding.get("capture_clock"))
    try:
        driver = service.oversold_daily
        if driver is None:
            raise RuntimeError("OVERSOLD_DAILY_OWNER_NOT_BOUND")
        key = driver.cursor_key(SOURCE_DAY, TARGET_DATE)
        initial, legacy_bridge = _recovery_cursor_preflight(service, key, SOURCE_DAY, TARGET_DATE)
        now = datetime.now(WORKBENCH_HK)
        triggered = driver.tick(source_day=SOURCE_DAY, target_date=TARGET_DATE, at=now)
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        terminal = {"SUCCEEDED", "PARTIAL_TERMINAL", "OWNER_READINESS_EXPIRED", "RETRY_EXHAUSTED"}
        final = service.store.cursor(key) or {}
        while time.monotonic() < deadline:
            state = str(final.get("state", "CANNOT_CONFIRM"))
            if state in terminal or state == "WAITING_FOR_PANEL_MASTER":
                break
            driver.tick(source_day=SOURCE_DAY, target_date=TARGET_DATE, at=datetime.now(WORKBENCH_HK))
            time.sleep(1)
            final = service.store.cursor(key) or {}
        else:
            state = str(final.get("state", "CANNOT_CONFIRM"))
            if state not in terminal and state != "WAITING_FOR_PANEL_MASTER":
                state = "CANNOT_CONFIRM"
        safe_fields = ("state", "operation", "source_hk_session", "target_date", "capture_attempts",
                       "job_attempts", "run_id", "job_id", "capture_run_id", "capture_manifest_sha256",
                       "panel_manifest_sha256", "master_manifest_sha256", "tdxpy_manifest_sha256", "last_error")
        print(json.dumps({
            "status": state,
            "source_day": SOURCE_DAY,
            "target_date": TARGET_DATE,
            "trigger_at": now.isoformat(),
            "trigger_result": triggered,
            "initial_cursor_state": (initial.get("state") if initial is not None
                                     else "MISSING_BOOTSTRAP_FROM_LEGACY_INPUT_MISSING"),
            "initial_cursor_provenance": {field: initial.get(field) for field in (
                "panel_manifest_sha256", "master_manifest_sha256", "tdxpy_manifest_sha256",
                "capture_run_id", "capture_manifest_sha256") if initial is not None and field in initial},
            "legacy_nextday_bridge": legacy_bridge,
            "active_scheduler_identity": active_identity,
            "final_cursor": {key: final.get(key) for key in safe_fields if key in final},
            "existing_exact_date_cursor_reused": initial is not None,
            "exact_date_cursor_bootstrapped_by_existing_driver": legacy_bridge is not None,
            "per_security_cache_hit_claim": "CANNOT_CONFIRM_WITHOUT_CAPTURE_RECORD_READBACK",
            "historical_cutoff_used": False,
            "old_plan_or_manual_work_deleted": False,
            "api_ui_and_natural_slot": "CANNOT_CONFIRM",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if state == "SUCCEEDED" else 4
    finally:
        service.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="print the exact-date recovery plan without running it")
    mode.add_argument("--run", action="store_true", help="perform one current-time recovery; may make bounded TDX requests")
    parser.add_argument("--authorization-ref")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.plan or not args.run:
        print(json.dumps({"status": "RECOVERY_PLAN_ONLY", "network_or_formal_run": False,
                          "source_day": SOURCE_DAY, "target_date": TARGET_DATE,
                          "trigger_time": "actual current Asia/Hong_Kong time",
                          "action": "resume only the existing exact-date OversoldDaily cursor; no historical cutoff",
                          "active_scheduler_identity_gate": "REQUIRED_ON_RUN",
                          "bound_release_id": ACTIVE_RELEASE_ID,
                          "bound_scheduler_pid": ACTIVE_PID,
                          "bound_plist_sha256": ACTIVE_PLIST_SHA256,
                          "bound_manifest_sha256": ACTIVE_MANIFEST_SHA256,
                          "bound_manager_config_sha256": ACTIVE_CONFIG_SHA256},
                         ensure_ascii=False, sort_keys=True))
        return 0
    if not args.authorization_ref or not args.authorization_ref.strip():
        parser.error("--run requires --authorization-ref")
    if args.child:
        try:
            return _child(args)
        except Exception as error:
            parser.exit(4, f"RECOVERY_CANNOT_CONFIRM:{type(error).__name__}:{str(error)[:240]}\n")
    if not ACTIVATION_RECEIPT.is_file():
        parser.error("prior candidate activation receipt is required before recovery")
    try:
        _validate_active_scheduler_identity()
    except Exception as error:
        parser.exit(4, f"RECOVERY_CANNOT_CONFIRM_ACTIVE_IDENTITY:{type(error).__name__}:{str(error)[:200]}\n")
    plist = plistlib.loads(ACTIVE_PLIST.read_bytes())
    env = dict(os.environ)
    env.update(plist.get("EnvironmentVariables", {}))
    app = ACTIVE_APP_ROOT
    runtime_root = Path(env["V35_RUNTIME_ROOT"])
    python = runtime_root / "venvs/v3.5-mac/bin/python"
    site_packages = runtime_root / "venvs/v3.5-mac/lib/python3.14/site-packages"
    if not python.is_file() or not site_packages.is_dir():
        parser.error("configured scheduler interpreter or site-packages unavailable")
    env["PYTHONPATH"] = f"{app}:{site_packages}:{app / 'upstreams'}:{app}"
    child = subprocess.run([str(python), "-S", str(Path(__file__).resolve()), "--run",
                            "--authorization-ref", args.authorization_ref, "--child"],
                           cwd=app, env=env, text=True, capture_output=True)
    if child.stdout:
        print(child.stdout, end="")
    if child.returncode:
        detail = child.stderr.strip().replace("\n", " ")[:400]
        parser.exit(child.returncode, f"RECOVERY_CANNOT_CONFIRM:{detail}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
