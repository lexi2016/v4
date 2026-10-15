#!/usr/bin/env python3
"""Plan-only by default; optionally resume the exact 20261015 -> 20261016 owner."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

DOC_ROOT = Path(__file__).resolve().parent
CANDIDATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-auto-20261016-r1")
STAGED_PLIST = CANDIDATE / "config/com.lexi.v35.scheduler.plist"
ACTIVATION_RECEIPT = DOC_ROOT / "scheduler_release_activation_receipt.json"
TARGET_DATE = "20261016"
SOURCE_DAY = "20261015"
HK = ZoneInfo("Asia/Hong_Kong")
MAX_WAIT_SECONDS = 3600


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child(args: argparse.Namespace) -> int:
    from v4.manager_workbench.binding import create_native_binding
    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import HK as WORKBENCH_HK
    from v4.manager_workbench.service import create_service

    manifest = CANDIDATE / "release-manifest.json"
    activation = json.loads(ACTIVATION_RECEIPT.read_text(encoding="utf-8"))
    if (activation.get("status") != "ACTIVATED_RUNTIME_ONLY"
            or activation.get("candidate_release_manifest_sha256") != _sha(manifest)):
        raise RuntimeError("CANDIDATE_ACTIVATION_RECEIPT_MISMATCH")
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
        initial = service.store.cursor(key)
        if not isinstance(initial, dict):
            raise RuntimeError("EXISTING_20261015_TO_20261016_CURSOR_MISSING")
        if initial.get("source_hk_session") != SOURCE_DAY or initial.get("target_date") != TARGET_DATE:
            raise RuntimeError("EXISTING_CURSOR_IDENTITY_MISMATCH")
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
            "initial_cursor_state": initial.get("state"),
            "initial_cursor_provenance": {key: initial.get(key) for key in (
                "panel_manifest_sha256", "master_manifest_sha256", "tdxpy_manifest_sha256",
                "capture_run_id", "capture_manifest_sha256") if key in initial},
            "final_cursor": {key: final.get(key) for key in safe_fields if key in final},
            "existing_exact_date_cursor_reused": True,
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
                          "action": "resume only the existing exact-date OversoldDaily cursor; no historical cutoff"},
                         ensure_ascii=False, sort_keys=True))
        return 0
    if not args.authorization_ref or not args.authorization_ref.strip():
        parser.error("--run requires --authorization-ref")
    if args.child:
        try:
            return _child(args)
        except Exception as error:
            parser.exit(4, f"RECOVERY_CANNOT_CONFIRM:{type(error).__name__}:{str(error)[:240]}\n")
    if not STAGED_PLIST.is_file() or not ACTIVATION_RECEIPT.is_file():
        parser.error("candidate activation and receipt are required before recovery")
    plist = plistlib.loads(STAGED_PLIST.read_bytes())
    env = dict(os.environ)
    env.update(plist.get("EnvironmentVariables", {}))
    app = CANDIDATE / "app"
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
