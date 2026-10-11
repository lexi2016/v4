#!/usr/bin/env python3
"""Capture the exact locked-Python no-fit start-registration command."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
REG = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration"
LOCKED = Path("/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13")
SCRIPT = REG / "register_r7_resume_readonly_preflight_03.py"
STDOUT = REG / "R7_RESUME_READONLY_PREFLIGHT_03_REGISTRAR_STDOUT.log"
STDERR = REG / "R7_RESUME_READONLY_PREFLIGHT_03_REGISTRAR_STDERR.log"
RECEIPT = REG / "R7_RESUME_READONLY_PREFLIGHT_03_REGISTRAR_COMMAND_RECEIPT.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    if sys.executable != str(LOCKED.resolve()):
        raise SystemExit("CAPTURE_WRAPPER_MUST_USE_EXPLICIT_LOCKED_PYTHON")
    if any(p.exists() or p.is_symlink() for p in (STDOUT, STDERR, RECEIPT)):
        raise SystemExit("REGISTRAR_CAPTURE_EXISTS_NO_OVERWRITE")
    env = dict(os.environ)
    env["PYTHON"] = str(LOCKED)
    argv = [str(LOCKED), "-I", "-B", str(SCRIPT)]
    result = subprocess.run(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    write_exclusive(STDOUT, result.stdout)
    write_exclusive(STDERR, result.stderr)
    receipt = {
        "schema": "BREADTH1_R7_PREFLIGHT_03_REGISTRAR_COMMAND_RECEIPT_V1",
        "status": "START_REGISTRATION_COMMAND_COMPLETED" if result.returncode == 0 else "START_REGISTRATION_COMMAND_FAILED",
        "cwd": str(ROOT),
        "argv": argv,
        "environment_python": env["PYTHON"],
        "resolved_sys_executable": str(LOCKED.resolve()),
        "registrar_path": str(SCRIPT.resolve()),
        "registrar_sha256": sha(SCRIPT),
        "stdout_path": str(STDOUT.resolve()),
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_path": str(STDERR.resolve()),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        "exit_code": result.returncode,
        "target_data_file_reads": 0,
        "model_loads": 0,
        "fit_calls": 0,
        "predict_calls": 0,
        "truth_reads": 0,
        "r7_action_debit": 0,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    write_exclusive(RECEIPT, (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
