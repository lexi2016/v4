#!/usr/bin/env python3
"""Run a temporary candidate/rollback API lifecycle on an isolated port.

This test never registers a LaunchAgent and never points the app at shared
manager, Stage, Vibe, scheduler, or trading state. It starts and stops only
child processes created by this invocation. It is an operational smoke test,
not a deployment or active-owner rollback receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import guarded_announcement_import as import_ops
import guarded_announcement_release as release_ops

TASK_ROOT = import_ops.TASK_ROOT
DEFAULT_PORT = 18873
RUNTIME_PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
DATA_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def isolated_environment(app_root: Path, sandbox: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("V4_", "V35_", "REVIEW_CORE_", "VIBE"))}
    manager = sandbox / "manager"
    data = sandbox / "data"
    stage = sandbox / "stage-selection"
    for path in (manager, data, stage):
        path.mkdir(parents=True, exist_ok=True)
    manifest = app_root.parent / "release-manifest.json"
    if not manifest.is_file():
        raise ValueError("ISOLATED_RELEASE_MANIFEST_MISSING")
    env.update({
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(manager),
        "V35_DATA_ROOT": str(data),
        "V35_RESEARCH_DATA_ROOT": str(data / "research"),
        "V35_SHARED_DATA_ROOT": str(data / "shared"),
        "V35_STAGE_CENTER_SELECTION_ROOT": str(stage),
        "V35_APP_ROOT": str(app_root.resolve()),
        "V35_RELEASE_ID": app_root.parent.name,
        "V35_RELEASE_MANIFEST_PATH": str(manifest.resolve()),
        "V35_RELEASE_MANIFEST_SHA256": digest(manifest.read_bytes()),
        "V35_RUNTIME_ROOT": str(Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime")),
        "PYTHONPATH": str(app_root / "upstreams") + ":" + str(app_root.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "RESEARCH_ONLY": "1", "production_allowed": "false", "PRODUCTION_ALLOWED": "false",
        "buy_gate_updated": "false", "BUY_GATE_UPDATED": "false", "orders_sent": "false", "ORDERS_SENT": "false",
        "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
        "NO_PROXY": "*", "no_proxy": "*",
    })
    return env


def assert_port_free(port: int) -> None:
    if port == 8873 or not (1024 <= port <= 65535):
        raise ValueError("ISOLATED_PORT_OUT_OF_ALLOWED_RANGE")
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ValueError("ISOLATED_PORT_NOT_AVAILABLE") from exc


def fetch_analysis(port: int) -> tuple[int, dict[str, Any], str]:
    query = urllib.parse.urlencode({"date": import_ops.TARGET_DATE,
                                    "publication_date": import_ops.PUBLICATION_DATE})
    url = f"http://127.0.0.1:{port}/api/v4/manager/research/announcements/analysis?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8")), digest(raw)


def verify_isolated_response(body: dict[str, Any]) -> dict[str, Any]:
    analysis = body.get("analysis") or {}
    source = body.get("source_catalog") or {}
    selection = analysis.get("stock_selection") or {}
    contract = {
        "target_trade_date": body.get("target_trade_date"),
        "publication_date": body.get("publication_date"),
        "analysis_status": analysis.get("status"), "source_status": source.get("status"),
        "selection_status": selection.get("status"),
        "production_allowed": body.get("production_allowed"),
        "buy_gate_updated": body.get("buy_gate_updated"), "orders_sent": body.get("orders_sent"),
        "research_only": body.get("RESEARCH_ONLY"),
    }
    for key, expected in (("target_trade_date", import_ops.TARGET_DATE),
                          ("publication_date", import_ops.API_PUBLICATION_DATE)):
        if contract[key] != expected:
            raise ValueError("ISOLATED_API_DATE_BINDING_MISMATCH:" + key)
        nested_date = analysis.get(key)
        if nested_date is not None and nested_date != expected:
            raise ValueError("ISOLATED_API_DATE_BINDING_MISMATCH:" + key)
    if (contract["analysis_status"] not in {"NOT_IMPORTED", "NOT_RUN"}
            or contract["source_status"] != "NOT_RUN"
            or contract["selection_status"] != "NOT_ASSESSED"
            or contract["production_allowed"] is not False
            or contract["buy_gate_updated"] is not False
            or contract["orders_sent"] is not False
            or contract["research_only"] is not True):
        raise ValueError("ISOLATED_API_EMPTY_STATE_OR_SAFETY_CONTRACT_FAILED")
    return contract


def run_child(app_root: Path, sandbox: Path, port: int) -> dict[str, Any]:
    if not RUNTIME_PYTHON.is_file() or not os.access(RUNTIME_PYTHON, os.X_OK):
        raise ValueError("ISOLATED_API_PYTHON_RUNTIME_MISSING")
    sandbox.mkdir(parents=True, exist_ok=False)
    log_path = sandbox / "api.log"
    env = isolated_environment(app_root, sandbox)
    command = [str(RUNTIME_PYTHON), "-B", "-m", "apps.api.v35_api.run", "--host", "127.0.0.1",
               "--port", str(port), "--stage-selection-root", str(sandbox / "stage-selection")]
    with log_path.open("wb") as log:
        child = subprocess.Popen(command, cwd=str(app_root), env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    started = datetime.now(timezone.utc).isoformat()
    last_error: str | None = None
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise ValueError("ISOLATED_API_CHILD_EXITED:" + str(child.returncode))
            try:
                status, body, raw_sha = fetch_analysis(port)
                if status != 200:
                    raise ValueError("ISOLATED_API_HTTP_STATUS:" + str(status))
                contract = verify_isolated_response(body)
                return {"status": "PASS_ISOLATED_API_READBACK", "pid": child.pid,
                        "app_root": str(app_root.resolve()), "started_at_utc": started,
                        "http_status": status, "raw_response_sha256": raw_sha,
                        "api_contract": contract, "log_path": str(log_path),
                        "command": command, "child": child}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                time.sleep(0.35)
        raise ValueError("ISOLATED_API_READBACK_TIMEOUT:" + str(last_error))
    except Exception:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        raise


def stop_child(child: subprocess.Popen) -> dict[str, Any]:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    if child.poll() is None:
        raise ValueError("ISOLATED_API_CHILD_CLEANUP_FAILED")
    return {"pid": child.pid, "returncode": child.returncode, "stopped": True}


def run_lifecycle(active_root: Path, staged_root: Path, port: int,
                  confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("ISOLATED_LIFECYCLE_CONFIRMATION_FLAG_REQUIRED")
    active_root = active_root.expanduser().resolve()
    staged_root = staged_root.expanduser().resolve()
    release_ops.assert_disjoint_release_paths(active_root, staged_root)
    assert_port_free(port)
    staged_verification = release_ops.verify_staged(active_root, staged_root)
    before = import_ops.launchd_owner_identity(active_root)
    run_root = TASK_ROOT / "daily_runs/20261007_20261006/isolated_lifecycle" / uuid4().hex
    run_root.mkdir(parents=True, exist_ok=False)
    stages: list[dict[str, Any]] = []
    children: list[subprocess.Popen] = []
    try:
        for label, app_root in (("baseline_before_candidate", active_root),
                                ("candidate", staged_root),
                                ("baseline_after_rollback", active_root)):
            record = run_child(app_root, run_root / label, port)
            child = record.pop("child")
            children.append(child)
            record["label"] = label
            record["stop"] = stop_child(child)
            stages.append(record)
        after = import_ops.launchd_owner_identity(active_root)
        if (before["pid"] != after["pid"] or before["active_root"] != after["active_root"]
                or before["plist_sha256"] != after["plist_sha256"]):
            raise ValueError("ACTIVE_8873_OWNER_CHANGED_DURING_ISOLATED_LIFECYCLE")
        receipt = {"schema": "v4.manager_research.announcement_isolated_release_lifecycle.v1",
            "status": "PASS_ISOLATED_CANDIDATE_AND_ROLLBACK_API_LIFECYCLE",
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "port": port,
            "active_8873_before": {key: before[key] for key in ("pid", "active_root", "plist_sha256")},
            "active_8873_after": {key: after[key] for key in ("pid", "active_root", "plist_sha256")},
            "isolated_app_stages": stages, "service_manager_mutation": False,
            "scheduler_or_launchd_registration": False, "shared_stage_or_vibe_state_used": False,
            "source_state_imported": False, "production_allowed": False, "buy_gate_updated": False,
            "orders_sent": False, "staged_release_preflight": staged_verification,
            "run_root": str(run_root)}
    except Exception as exc:
        receipt = {"schema": "v4.manager_research.announcement_isolated_release_lifecycle.v1",
            "status": "ISOLATED_LIFECYCLE_INDETERMINATE", "error": f"{type(exc).__name__}:{exc}",
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "port": port,
            "isolated_app_stages": stages, "run_root": str(run_root),
            "service_manager_mutation": False, "scheduler_or_launchd_registration": False}
        raise
    finally:
        for child in children:
            if child.poll() is None:
                stop_child(child)
        path = run_root / "receipt.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-release-root", type=Path, default=release_ops.DEFAULT_ACTIVE_RELEASE)
    parser.add_argument("--staged-release-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--confirm-isolated-lifecycle", action="store_true")
    args = parser.parse_args()
    try:
        value = run_lifecycle(args.active_release_root, args.staged_release_root,
                              args.port, args.confirm_isolated_lifecycle)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
