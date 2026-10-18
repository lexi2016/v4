#!/usr/bin/env python3
"""Prepare an inactive API-only plist cutover and a frozen rollback snapshot.

This script never writes the live LaunchAgent plist, calls launchctl, touches
manager state/config, changes the release manifest/source, or submits a run.
It stages the candidate plist using the existing API-only rewrite helper.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
HANDOFF_ROOT = REPO_ROOT / "docs/handoffs/us_friday_close_backfill_20261018"
LOCAL_ROOT = HANDOFF_ROOT / "local_only/api_activation"
ACTIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CONFIG_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/config/"
    "us-hk-recovery-v2r1-20261016-r2.json"
)
ACTIVE_RELEASE_ID = "announcement-contract-repair-20261018-r4"
ACTIVE_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "announcement-contract-repair-20261018-r4"
)
CANDIDATE_RELEASE_ID = "friday-close-input-api-20261018-r1"
CANDIDATE_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "friday-close-input-api-20261018-r1"
)
CANDIDATE_MANIFEST = CANDIDATE_RELEASE_ROOT / "release-manifest.json"
CANDIDATE_PLIST = CANDIDATE_RELEASE_ROOT / "config/com.lexi.v35.api-only.plist"
PLAN_PATH = HANDOFF_ROOT / "API_ACTIVATION_PLAN.json"
RECEIPT_PATH = LOCAL_ROOT / "preparation_receipt.json"
BACKUP_PLIST = LOCAL_ROOT / "active_com.lexi.v35.api-only.before_candidate.plist"

REWRITE_KEYS = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "PYTHONPATH",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
}
EXPECTED_PREIMAGE = {
    "active_plist_sha256": "38a71ac87ee83c1c04f4078e1c99cd07aa464ed08ff9b209beaffb84785377fb",
    "active_config_sha256": "589eaa058b9abd9cef59ab71ef2c3f4c3c998bae18dd26777134bf0fa22ef86e",
    "active_manifest_sha256": "1d2adb1894bcb91baacf2396516409db1b2fd71755795675e81cfbed292f190b",
    "candidate_manifest_sha256": "0865254e40584da570cfd93aabfdd77c6f9bf8b38a8ca6ba30eb8fcc84d54bba",
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def assignments(plist: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in plist.get("ProgramArguments", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key and not any(ch.isspace() for ch in key):
                values[key] = value
    env = plist.get("EnvironmentVariables", {})
    if isinstance(env, dict):
        for key, value in env.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                values[key] = str(value)
    return values


def normalized_plist(plist: dict[str, Any]) -> dict[str, Any]:
    """Mask only the supported API release identity fields for equality."""
    result = copy.deepcopy(plist)
    args = result.get("ProgramArguments")
    if isinstance(args, list):
        result["ProgramArguments"] = [
            f"{item.split('=', 1)[0]}=<release-identity>"
            if isinstance(item, str)
            and "=" in item
            and item.split("=", 1)[0] in REWRITE_KEYS
            else item
            for item in args
        ]
    env = result.get("EnvironmentVariables")
    if isinstance(env, dict):
        result["EnvironmentVariables"] = {
            key: "<release-identity>" if key in REWRITE_KEYS else value
            for key, value in env.items()
        }
    result["WorkingDirectory"] = "<release-identity>"
    return result


def process_identity(expected_app_root: Path) -> dict[str, Any]:
    ps = subprocess.run(
        ["/bin/ps", "-axo", "pid=,lstart=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    matches: list[tuple[int, str, str]] = []
    for line in ps.stdout.splitlines():
        parts = line.strip().split(None, 6)
        if len(parts) < 7:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        started = " ".join(parts[1:6])
        command = parts[6]
        if "apps.api.v35_api.run" in command and "--port 8873" in command:
            matches.append((pid, started, command))
    if len(matches) != 1:
        raise RuntimeError("API_PROCESS_IDENTITY_NOT_UNIQUE")
    pid, started, command = matches[0]
    # Keep the recorded command minimal; no process environment is read.
    if "python" not in command.lower():
        raise RuntimeError("API_PROCESS_EXECUTABLE_UNEXPECTED")
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    cwd_result = subprocess.run(
        [lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=True,
        capture_output=True,
        text=True,
    )
    cwd = next((line[1:] for line in cwd_result.stdout.splitlines() if line.startswith("n")), None)
    if cwd is None or Path(cwd).resolve() != expected_app_root.resolve():
        raise RuntimeError("API_PROCESS_CWD_DOES_NOT_MATCH_ACTIVE_RELEASE")
    owner_result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "uid="],
        check=True,
        capture_output=True,
        text=True,
    )
    owner_uid = owner_result.stdout.strip()
    if owner_uid != str(os.getuid()):
        raise RuntimeError("API_PROCESS_GUI_UID_MISMATCH")
    return {
        "pid": pid,
        "started_local": started,
        "working_directory": cwd,
        "listen_port": 8873,
        "gui_uid": owner_uid,
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from ops.api_release_integration import api_release_lock_path
    from ops.prepare_api_only_cutover import rewrite_api_only_plist

    if not ACTIVE_PLIST.is_file() or not CONFIG_PATH.is_file():
        raise FileNotFoundError("ACTIVE_API_PLIST_OR_MANAGER_CONFIG_MISSING")
    if not CANDIDATE_MANIFEST.is_file() or not (CANDIDATE_RELEASE_ROOT / "app").is_dir():
        raise FileNotFoundError("INACTIVE_API_CANDIDATE_MISSING")
    if CANDIDATE_PLIST.is_symlink():
        raise RuntimeError("CANDIDATE_API_PLIST_MUST_NOT_BE_SYMLINK")

    active_plist_raw = ACTIVE_PLIST.read_bytes()
    config_raw = CONFIG_PATH.read_bytes()
    candidate_manifest_raw = CANDIDATE_MANIFEST.read_bytes()
    active_plist_sha = sha256_bytes(active_plist_raw)
    config_sha = sha256_bytes(config_raw)
    candidate_manifest_sha = sha256_bytes(candidate_manifest_raw)
    active_plist = plistlib.loads(active_plist_raw)
    active_values = assignments(active_plist)

    if active_plist_sha != EXPECTED_PREIMAGE["active_plist_sha256"]:
        raise RuntimeError("ACTIVE_API_PLIST_PREIMAGE_CHANGED")
    if config_sha != EXPECTED_PREIMAGE["active_config_sha256"]:
        raise RuntimeError("MANAGER_CONFIG_PREIMAGE_CHANGED")
    if candidate_manifest_sha != EXPECTED_PREIMAGE["candidate_manifest_sha256"]:
        raise RuntimeError("CANDIDATE_MANIFEST_PREIMAGE_CHANGED")
    if active_values.get("V35_RELEASE_ID") != ACTIVE_RELEASE_ID:
        raise RuntimeError("ACTIVE_API_RELEASE_ID_MISMATCH")
    if Path(active_values.get("V35_APP_ROOT", "")).resolve() != (
        ACTIVE_RELEASE_ROOT / "app"
    ).resolve():
        raise RuntimeError("ACTIVE_API_APP_ROOT_MISMATCH")
    active_manifest = Path(active_values.get("V35_RELEASE_MANIFEST_PATH", ""))
    if active_manifest != ACTIVE_RELEASE_ROOT / "release-manifest.json":
        raise RuntimeError("ACTIVE_API_MANIFEST_PATH_MISMATCH")
    if active_values.get("V35_RELEASE_MANIFEST_SHA256") != EXPECTED_PREIMAGE["active_manifest_sha256"]:
        raise RuntimeError("ACTIVE_API_MANIFEST_IDENTITY_MISMATCH")
    if sha256_file(active_manifest) != EXPECTED_PREIMAGE["active_manifest_sha256"]:
        raise RuntimeError("ACTIVE_API_MANIFEST_BYTES_MISMATCH")
    if active_values.get("V4_MANAGER_WORKBENCH_CONFIG_PATH") != str(CONFIG_PATH):
        raise RuntimeError("MANAGER_WORKBENCH_CONFIG_PATH_CHANGED")

    process = process_identity(Path(active_values["V35_APP_ROOT"]))
    candidate_app = CANDIDATE_RELEASE_ROOT / "app"
    staged = rewrite_api_only_plist(
        active_plist,
        candidate_app_root=candidate_app,
        release_id=CANDIDATE_RELEASE_ID,
        manifest_path=CANDIDATE_MANIFEST,
        manifest_sha256=candidate_manifest_sha,
    )
    staged_raw = plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True)
    reparsed = plistlib.loads(staged_raw)
    if reparsed != staged:
        raise RuntimeError("CANDIDATE_PLIST_PARSE_MISMATCH")
    if normalized_plist(active_plist) != normalized_plist(staged):
        raise RuntimeError("CANDIDATE_PLIST_NONIDENTITY_DRIFT")
    staged_values = assignments(staged)
    expected_values = {
        "V35_APP_ROOT": str(candidate_app.resolve()),
        "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
        "PYTHONPATH": f"{candidate_app.resolve() / 'upstreams'}:{candidate_app.resolve()}",
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_MANIFEST.resolve()),
        "V35_RELEASE_MANIFEST_SHA256": candidate_manifest_sha,
        "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(CONFIG_PATH),
    }
    for key, value in expected_values.items():
        if staged_values.get(key) != value:
            raise RuntimeError("CANDIDATE_PLIST_IDENTITY_VALUE_MISMATCH:" + key)
    if staged.get("WorkingDirectory") != str(candidate_app.resolve()):
        raise RuntimeError("CANDIDATE_WORKING_DIRECTORY_MISMATCH")

    label = active_plist.get("Label")
    if label != "com.lexi.v35.api-only":
        raise RuntimeError("ACTIVE_API_LAUNCHD_LABEL_MISMATCH")
    uid = process["gui_uid"]
    launchd_domain = f"gui/{uid}"
    active_target = f"{launchd_domain}/{label}"
    shared_lock = api_release_lock_path(ACTIVE_PLIST)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    plan = {
        "schema_version": "v4.friday_api_activation_plan.v1",
        "generated_at_utc": generated_at,
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "live_plist_written": False,
        "manager_config_or_state_changed": False,
        "preconditions": [
            "Independent API candidate review must PASS before activation.",
            "Immediately revalidate PID, active root, active plist/config/manifest SHA, candidate manifest SHA, and API canary under the existing shared API release lock.",
            "Use the existing API-only integration path; preserve manager state/config and all non-release environment values.",
            "The argv below are descriptive only and use the GUI uid captured from the live API process; this script does not execute them.",
        ],
        "shared_api_release_lock_path": str(shared_lock),
        "launchd_gui_domain": launchd_domain,
        "active": {
            "pid_snapshot": process,
            "launchd_label": label,
            "plist_path": str(ACTIVE_PLIST),
            "plist_sha256": active_plist_sha,
            "release_id": ACTIVE_RELEASE_ID,
            "release_root": str(ACTIVE_RELEASE_ROOT),
            "app_root": active_values["V35_APP_ROOT"],
            "manifest_path": str(active_manifest),
            "manifest_sha256": active_values["V35_RELEASE_MANIFEST_SHA256"],
            "manager_config_path": str(CONFIG_PATH),
            "manager_config_sha256": config_sha,
        },
        "candidate": {
            "release_id": CANDIDATE_RELEASE_ID,
            "release_root": str(CANDIDATE_RELEASE_ROOT),
            "app_root": str(candidate_app.resolve()),
            "manifest_path": str(CANDIDATE_MANIFEST),
            "manifest_sha256": candidate_manifest_sha,
            "staged_plist_path": str(CANDIDATE_PLIST),
            "staged_plist_sha256": sha256_bytes(staged_raw),
            "manager_config_path_preserved": str(CONFIG_PATH),
            "manager_config_sha256_preserved": config_sha,
        },
        "rollback_backup": {
            "path": str(BACKUP_PLIST),
            "sha256": active_plist_sha,
            "byte_identical_to_active_preimage": True,
        },
        "plist_identity_switches": [
            "V35_APP_ROOT",
            "V35_RELEASE_ID",
            "PYTHONPATH",
            "V35_RELEASE_MANIFEST_PATH",
            "V35_RELEASE_MANIFEST_SHA256",
            "WorkingDirectory",
        ],
        "preserved_environment": True,
        "activation_subprocess_argv": [
            ["launchctl", "bootout", active_target],
            ["launchctl", "bootstrap", launchd_domain, str(CANDIDATE_PLIST)],
        ],
        "rollback_subprocess_argv": [
            ["launchctl", "bootout", active_target],
            ["/bin/cp", str(BACKUP_PLIST), str(ACTIVE_PLIST)],
            ["launchctl", "bootstrap", launchd_domain, str(ACTIVE_PLIST)],
        ],
        "post_action_readback": [
            ["launchctl", "print", active_target],
            ["/usr/bin/shasum", "-a", "256", str(ACTIVE_PLIST)],
        ],
    }

    receipt = {
        "schema_version": "v4.friday_api_activation_preparation_receipt.v1",
        "prepared_at_utc": generated_at,
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "active_plist_written": False,
        "manager_config_or_state_written": False,
        "selector_submitted": False,
        "api_ui_readback_performed": False,
        "active": plan["active"],
        "candidate": plan["candidate"],
        "backup": {
            "path": str(BACKUP_PLIST),
            "sha256": active_plist_sha,
            "size_bytes": len(active_plist_raw),
            "byte_identical_to_active_preimage": True,
        },
        "preserved_environment": True,
        "plist_identity_switches": plan["plist_identity_switches"],
        "unresolved": [
            "Independent API candidate/config review pending.",
            "Activation and rollback have not been executed.",
            "Post-activation API/UI selection behavior remains CANNOT_CONFIRM.",
        ],
    }

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    if BACKUP_PLIST.exists():
        if BACKUP_PLIST.read_bytes() != active_plist_raw:
            raise RuntimeError("EXISTING_ACTIVE_PLIST_BACKUP_MISMATCH")
    else:
        BACKUP_PLIST.write_bytes(active_plist_raw)
    os.chmod(BACKUP_PLIST, ACTIVE_PLIST.stat().st_mode & 0o777)
    if BACKUP_PLIST.read_bytes() != active_plist_raw:
        raise RuntimeError("ACTIVE_PLIST_BACKUP_BYTE_MISMATCH")

    CANDIDATE_PLIST.parent.mkdir(parents=True, exist_ok=True)
    if CANDIDATE_PLIST.exists():
        if CANDIDATE_PLIST.read_bytes() != staged_raw:
            raise RuntimeError("EXISTING_CANDIDATE_API_PLIST_DRIFT")
    else:
        CANDIDATE_PLIST.write_bytes(staged_raw)
        os.chmod(CANDIDATE_PLIST, ACTIVE_PLIST.stat().st_mode & 0o777)
    if plistlib.loads(CANDIDATE_PLIST.read_bytes()) != staged:
        raise RuntimeError("STAGED_CANDIDATE_PLIST_READBACK_MISMATCH")
    if sha256_bytes(ACTIVE_PLIST.read_bytes()) != active_plist_sha:
        raise RuntimeError("ACTIVE_API_PLIST_CHANGED_DURING_PREPARATION")
    if sha256_file(CONFIG_PATH) != config_sha:
        raise RuntimeError("MANAGER_CONFIG_CHANGED_DURING_PREPARATION")
    if sha256_file(CANDIDATE_MANIFEST) != candidate_manifest_sha:
        raise RuntimeError("CANDIDATE_MANIFEST_CHANGED_DURING_PREPARATION")

    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return plan, receipt


def main() -> int:
    plan, receipt = build()
    print(json.dumps({"plan": plan, "receipt": receipt}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
